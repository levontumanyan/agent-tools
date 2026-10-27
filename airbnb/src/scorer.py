import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

try:
	from amenities import evaluate_kitchen, has_amenity
	from climate import get_climate_profile
except ImportError:
	from src.amenities import evaluate_kitchen, has_amenity
	from src.climate import get_climate_profile

logger = logging.getLogger("airbnb")


class ScoreResult(tuple):
	"""Tuple subclass containing (final_score, applied_penalties) with flags and kitchen_tier attributes."""

	def __new__(cls, score, penalties, flags=None, kitchen_tier=None):
		return super().__new__(cls, (score, penalties))

	def __init__(self, score, penalties, flags=None, kitchen_tier=None):
		self.score = score
		self.penalties = penalties
		self.flags = flags or []
		self.kitchen_tier = kitchen_tier


class Scorer:
	def __init__(
		self,
		benchmarks,
		num_nights=1,
		require_fast_wifi=False,
		market_median_price=None,
		check_in=None,
		check_out=None,
	):
		self.benchmarks = benchmarks
		self.metrics = benchmarks.get("metrics", {})
		self.penalties = benchmarks.get("penalties", [])
		self.hard_filters = benchmarks.get("hard_filters", {})
		self.num_nights = num_nights
		self.require_fast_wifi = require_fast_wifi
		self.market_median_price = market_median_price
		self.check_in = check_in
		self.check_out = check_out
		self.last_flags = []
		self.last_kitchen_tier = None
		self.last_climate = None

	def calculate_score(self, listing_details):
		"""
		Calculates the final score for a listing based on benchmarks.
		Returns ScoreResult((final_score, applied_penalties), flags=flags, kitchen_tier=kitchen_tier).
		"""
		# 1. Review evidence & kitchen evaluation
		evidence = self.extract_review_evidence(listing_details)
		kitchen_info = evaluate_kitchen(listing_details, evidence)
		kitchen_tier = kitchen_info.get("tier")
		flags = list(kitchen_info.get("flags", []))

		# 2. Check Hard Filters
		passed, failed_filters = self._passes_hard_filters(listing_details)
		if not passed:
			logger.info(
				f"  Listing failed hard filters: {', '.join(failed_filters)}. Score: 0"
			)
			failed_penalties = [f"FAILED: {f}" for f in failed_filters]
			failed_flags = [f"[DISQUALIFIED: {f}]" for f in failed_filters] + flags
			self.last_flags = failed_flags
			self.last_kitchen_tier = kitchen_tier
			return ScoreResult(
				0, failed_penalties, flags=failed_flags, kitchen_tier=kitchen_tier
			)

		# 3. Calculate Base Score
		# If market_median_price is not provided (e.g. single listing inspection),
		# ignore the market_relative value metric when other metrics exist and re-normalize them.
		has_other_metrics = any(
			name != "value" and cfg.get("weight", 0) > 0
			for name, cfg in self.metrics.items()
		)
		active_metrics = {}
		for name, config in self.metrics.items():
			func_name = config.get("function")
			if (
				name == "value"
				and func_name == "market_relative"
				and self.market_median_price is None
				and has_other_metrics
			):
				continue
			active_metrics[name] = config

		total_weight = sum(cfg.get("weight", 0) for cfg in active_metrics.values())
		scale_factor = (1.0 / total_weight) if total_weight > 0 else 1.0

		base_score = 0
		for name, config in active_metrics.items():
			func_name = config.get("function")
			raw_weight = config.get("weight", 0)
			normalized_weight = raw_weight * scale_factor
			params = config.get("params", {})

			metric_score = self._run_metric_function(func_name, listing_details, params)
			weighted_score = metric_score * normalized_weight
			base_score += weighted_score
			logger.debug(
				f"  Metric {name}: {metric_score:.2f} (weight {normalized_weight:.2f}) -> {weighted_score:.2f}"
			)

		# 4. Check Wi-Fi flag
		wifi_info = self.detect_fast_wifi(listing_details)
		if not wifi_info.get("verified") and "[FLAG: Standard Wi-Fi]" not in flags:
			flags.append("[FLAG: Standard Wi-Fi]")

		# 5. Climate & Season-Aware Comfort Profile
		coords = listing_details.get("coordinates") or {}
		lat = (
			coords.get("latitude")
			or coords.get("lat")
			or listing_details.get("lat")
			or listing_details.get("latitude")
		)
		lon = (
			coords.get("longitude")
			or coords.get("lng")
			or listing_details.get("lng")
			or listing_details.get("longitude")
		)
		climate = None
		if lat is not None and lon is not None:
			try:
				climate = get_climate_profile(
					float(lat), float(lon), self.check_in, self.check_out
				)
				self.last_climate = climate
			except Exception as e:
				logger.debug(f"Climate evaluation error: {e}")

		# 6. Apply Declarative Penalties
		final_score = base_score
		applied_penalties = []

		for penalty in self.penalties:
			p_type = penalty.get("type")
			p_id = penalty.get("id")
			triggered = False

			if p_type == "missing_amenity":
				amenity = penalty.get("amenity")
				if amenity == "ac" or p_id == "missing_ac":
					has_ac = has_amenity(listing_details, "ac")
					ac_needed = climate.get("ac_needed", True) if climate else True
					if not has_ac:
						if ac_needed:
							triggered = True
						else:
							if "[INFO: Mild Climate (AC Optional)]" not in flags:
								flags.append("[INFO: Mild Climate (AC Optional)]")
					else:
						if not ac_needed and "[FEATURE: AC (Bonus)]" not in flags:
							flags.append("[FEATURE: AC (Bonus)]")
				else:
					if not has_amenity(listing_details, amenity):
						triggered = True
			elif p_type == "kitchen_tier":
				disallowed = penalty.get(
					"disallowed_tiers", ["kitchenette", "no_kitchen"]
				)
				allowed = penalty.get("allowed_tiers")
				if (allowed and kitchen_tier not in allowed) or (
					disallowed and kitchen_tier in disallowed
				):
					triggered = True
			elif p_type == "review_signal":
				signal_field = penalty.get("signal_field")
				if evidence.get(signal_field):
					triggered = True
			elif penalty.get("condition"):
				if self._check_condition(penalty.get("condition"), listing_details):
					triggered = True

			if triggered:
				multiplier = penalty.get("multiplier", 1.0)
				final_score *= multiplier
				p_name = penalty.get("name", "Penalty")
				applied_penalties.append(p_name)
				logger.info(f"  Penalty Applied: {p_name} ({multiplier}x)")
				flag = penalty.get("flag")
				if flag and flag not in flags:
					flags.append(flag)

		# Dynamic Climate: Heating Evaluation for cool/chilly nights
		if climate and climate.get("heating_needed"):
			has_heating = has_amenity(listing_details, "heating")
			if not has_heating:
				final_score *= 0.95
				applied_penalties.append("Missing Heating (Cold Nights)")
				if "[FLAG: No Heating (Cold Nights)]" not in flags:
					flags.append("[FLAG: No Heating (Cold Nights)]")
			else:
				if "[FEATURE: Heating]" not in flags:
					flags.append("[FEATURE: Heating]")

		# Multi-layer Noise Evaluation (Highlights, Host Description, Guest Reviews)
		noise_info = self.detect_noise_profile(listing_details)
		for f in noise_info.get("flags", []):
			if f not in flags:
				flags.append(f)

		if noise_info["has_risk"] and not any("Noise" in p for p in applied_penalties):
			final_score *= 0.75
			applied_penalties.append("Noise Risk (0.75x)")
			logger.info("  Penalty Applied: Noise Risk (0.75x)")

		final_score = round(final_score, 2)
		self.last_flags = flags
		self.last_kitchen_tier = kitchen_tier
		return ScoreResult(
			final_score, applied_penalties, flags=flags, kitchen_tier=kitchen_tier
		)

	def _passes_hard_filters(self, listing):
		# Check must_have_amenities
		must_haves = self.hard_filters.get("must_have_amenities", [])
		failed_filters = []
		if must_haves:
			for must_have in must_haves:
				if not has_amenity(listing, must_have):
					logger.info(f"  Missing must-have amenity: {must_have}")
					failed_filters.append(f"Missing {must_have}")

		# Check Fast Wi-Fi requirement if flag is set
		if self.require_fast_wifi:
			wifi_info = self.detect_fast_wifi(listing)
			if not wifi_info.get("verified"):
				logger.info(f"  Missing verified fast wifi: {wifi_info.get('details')}")
				failed_filters.append("Missing verified fast wifi")

		if failed_filters:
			return False, failed_filters
		return True, []

	def _run_metric_function(self, func_name, listing, params):
		if func_name == "percentage_match":
			return self._percentage_match(listing, params)
		elif func_name == "market_relative":
			if self.market_median_price is not None and self.market_median_price > 0:
				return self._market_relative(listing, params)
			return self._fixed_decay(listing, params)
		elif func_name == "fixed_decay":
			return self._fixed_decay(listing, params)
		elif func_name == "keyword_analysis":
			return self._keyword_analysis(listing, params)
		return 0

	def _check_condition(self, condition, listing):
		if not condition:
			return False

		field = condition.get("field")
		operator = condition.get("operator")
		target_value = condition.get("value")

		actual_value = 0
		if field == "review_count":
			try:
				actual_value = int(listing.get("rating", {}).get("review_count", 0))
			except (ValueError, TypeError):
				actual_value = 0
		elif field == "review_score":
			# guest_satisfaction is often 0-100 or 0-5 depending on API
			try:
				actual_value = float(
					listing.get("rating", {}).get("guest_satisfaction", 0)
				)
				# If guest_satisfaction is e.g. 96 (percent), and target is 4.5 (stars), normalize
				if actual_value > 5 and target_value <= 5:
					actual_value = actual_value / 20.0
			except (ValueError, TypeError):
				actual_value = 0

		if operator == "<":
			return actual_value < target_value
		elif operator == ">":
			return actual_value > target_value
		elif operator == "==":
			return actual_value == target_value

		return False

	# --- Metric Functions (Stubs) ---

	def _percentage_match(self, listing, params):
		bonus = params.get("bonus_amenities", [])
		if not bonus:
			return 100

		matches = 0
		for b in bonus:
			if has_amenity(listing, b):
				matches += 1

		return (matches / len(bonus)) * 100

	def _fixed_decay(self, listing, params):
		total_price = listing.get("price", {}).get("amount", 0)
		daily_price = (
			total_price / self.num_nights if self.num_nights > 0 else total_price
		)
		decay_rate = params.get("decay_rate", 0.2)

		# 100 points minus the daily price multiplied by the decay rate. Minimum 0.
		score = 100.0 - (daily_price * decay_rate)
		return max(0.0, min(100.0, score))

	def _market_relative(self, listing, params):
		"""
		Evaluates listing price relative to the dynamic regional market median.
		- ratio <= target_ratio (e.g. 0.80, 20% below median): 100 points
		- ratio == base_ratio (1.0, at median): 80 points
		- ratio > 1.0 (above median): drops smoothly from 80 down to 0 at ratio 2.0
		"""
		if not self.market_median_price or self.market_median_price <= 0:
			return 80.0

		price_dict = listing.get("price") or {}
		nightly = price_dict.get("nightly")
		if nightly is None:
			total_price = float(price_dict.get("amount") or 0)
			nightly = (
				total_price / self.num_nights if self.num_nights > 0 else total_price
			)

		if nightly <= 0:
			return 0.0

		ratio = nightly / self.market_median_price
		target_ratio = params.get("target_ratio", 0.80)
		base_ratio = params.get("base_ratio", 1.0)

		if ratio <= target_ratio:
			return 100.0
		elif ratio <= base_ratio:
			fraction = (ratio - target_ratio) / (base_ratio - target_ratio)
			return round(100.0 - (fraction * 20.0), 2)
		else:
			score = 80.0 - ((ratio - 1.0) * 80.0)
			return round(max(0.0, min(100.0, score)), 2)

	def _parse_review_recency_weight(self, review: Dict[str, Any]) -> Tuple[float, str]:
		"""
		Computes recency decay weight based on review creation date:
		- Under 12 months: 1.0 (recent, highly relevant)
		- 12 to 24 months: 0.5 (older, moderate relevance)
		- Over 24 months:  0.2 (historical, low relevance)
		- Undated/fallback: 0.8
		"""
		created_at = review.get("createdAt") or review.get("created_at")
		if not created_at:
			return 0.8, "undated"
		try:
			if isinstance(created_at, str):
				dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
				ref_tz = dt.tzinfo or timezone.utc
				now_dt = datetime.now(ref_tz)
				days_old = max(0, (now_dt - dt).days)
				if days_old <= 365:
					return 1.0, f"{days_old // 30}mo ago"
				elif days_old <= 730:
					return 0.5, "1-2y ago"
				else:
					return 0.2, f"{days_old // 365}y ago"
		except Exception:
			pass
		return 0.8, "undated"

	def _keyword_analysis(self, listing, params):
		reviews = listing.get("reviews", [])
		if not reviews:
			return 80.0

		pos_keywords = [
			k.lower()
			for k in params.get(
				"positive_keywords",
				[
					"clean",
					"quiet",
					"comfortable",
					"fast wifi",
					"tranquilo",
					"escritorio",
					"fibra",
					"zoom",
				],
			)
		]
		neg_keywords = [
			k.lower()
			for k in params.get(
				"negative_keywords",
				[
					"loud",
					"dirty",
					"smell",
					"slow wifi",
					"ruido",
					"sin mesa",
					"no hot water",
					"cold water",
				],
			)
		]

		pos_count = 0.0
		neg_count = 0.0

		for r in reviews:
			weight, _ = self._parse_review_recency_weight(r)
			comment = (r.get("comments") or "").lower()
			for p in pos_keywords:
				if p in comment:
					pos_count += weight
			for n in neg_keywords:
				if n in comment:
					neg_count += weight

		# Score baseline at 80, boosted by positive keywords, penalized by negative
		score = 80.0 + min(20.0, pos_count * 2.0) - (neg_count * 5.0)
		return max(0.0, min(100.0, score))

	def detect_noise_profile(self, listing):
		"""
		Multi-layer noise evaluation across 3 layers:
		1. Highlights (Official Airbnb badges e.g. 'Quiet area' / 'Zona tranquila')
		2. Description (Host declarations of soundproofing / double-glazing vs noise warnings)
		3. Reviews (Guest noise complaints vs quiet confirmations)
		"""
		desc = f"{listing.get('description', '')} {listing.get('title', '')}".lower()
		soundproof_regex = re.compile(
			r"\b(antiruido|vidrios?\s+dobles?|doble\s+vidrio|termoac[uú]stico|insonorizado|soundproof(?:ed)?|double-pane|double\s+glazing)\b",
			re.I,
		)
		noise_warning_regex = re.compile(
			r"\b(puede\s+haber\s+ruido|zona\s+concurrida|calle\s+transitada|some\s+street\s+noise|busy\s+street|hear\s+noise)\b",
			re.I,
		)

		evidence = self.extract_review_evidence(listing)
		has_noise_complaint = bool(evidence.get("noise_negative"))
		has_quiet_reviews = len(evidence.get("noise_positive", [])) >= 2
		has_soundproof_claim = bool(soundproof_regex.search(desc))
		has_noise_warning = bool(noise_warning_regex.search(desc))

		flags = []
		if has_noise_complaint or has_noise_warning:
			flags.append("[FLAG: Noise Risk]")
		elif has_soundproof_claim:
			flags.append("[FEATURE: Soundproof Windows]")
		elif has_quiet_reviews:
			flags.append("[SIGNAL: Verified Quiet]")

		return {
			"has_risk": has_noise_complaint or has_noise_warning,
			"soundproof_windows": has_soundproof_claim,
			"verified_quiet": has_quiet_reviews,
			"flags": flags,
		}

	def detect_fast_wifi(self, listing):
		"""
		Detects verified fast wifi across 4 layers:
		1. Highlights (Official Airbnb badge e.g. 'Fast wifi' / 50+ Mbps)
		2. Amenities (Wifi subtitle with verified Mbps)
		3. Description (Host fiber/speed declaration)
		4. Reviews (Guest speed tests or remote work confirmations)
		"""
		# 1. Highlights
		for h in listing.get("highlights", []):
			htitle = str(h.get("title") or "").lower()
			hsub_raw = h.get("subtitle")
			hsub = (
				hsub_raw.get("htmlText") or hsub_raw.get("text") or str(hsub_raw)
				if isinstance(hsub_raw, dict)
				else str(hsub_raw or "")
			).lower()
			if (
				"fast wifi" in htitle
				or "wifi rápido" in htitle
				or "wifi veloz" in htitle
				or "mbps" in hsub
				or "mbps" in htitle
			):
				speed_match = re.search(
					r"(\d+)\s*mbps", f"{htitle} {hsub}", re.IGNORECASE
				)
				speed = int(speed_match.group(1)) if speed_match else 50
				return {
					"verified": True,
					"source": "badge",
					"speed_mbps": speed,
					"details": h.get("title") or "Airbnb Fast Wifi Badge",
				}

		# 2. Amenities
		for cat in listing.get("amenities", []):
			for val in cat.get("values", []):
				vtitle = str(val.get("title") or "").lower()
				vsub_raw = val.get("subtitle")
				vsub = (
					vsub_raw.get("htmlText") or vsub_raw.get("text") or str(vsub_raw)
					if isinstance(vsub_raw, dict)
					else str(vsub_raw or "")
				).lower()
				if ("wifi" in vtitle or "internet" in vtitle) and "mbps" in vsub:
					speed_match = re.search(r"(\d+)\s*mbps", vsub, re.IGNORECASE)
					speed = int(speed_match.group(1)) if speed_match else None
					detail_str = (
						vsub_raw.get("htmlText")
						or vsub_raw.get("text")
						or str(vsub_raw)
						if isinstance(vsub_raw, dict)
						else str(vsub_raw or "")
					)
					return {
						"verified": True,
						"source": "amenity",
						"speed_mbps": speed,
						"details": f"Amenity verified: {detail_str}",
					}

		# 3. Description
		desc = listing.get("description", "") or ""
		speed_match = re.search(r"(\d+)\s*(?:mbps|megas|mb)\b", desc, re.IGNORECASE)
		fiber_match = re.search(
			r"\b(fibra\s*[\w\s]{0,15}|fiber\s*[\w\s]{0,15})\b", desc, re.IGNORECASE
		)
		if speed_match or fiber_match:
			speed = int(speed_match.group(1)) if speed_match else None
			detail = speed_match.group(0) if speed_match else fiber_match.group(0)
			return {
				"verified": True,
				"source": "description",
				"speed_mbps": speed,
				"details": f"Host description: {detail}",
			}

		# 4. Reviews
		for r in listing.get("reviews", []):
			com = (r.get("comments") or "").lower()
			speed_match = re.search(r"(\d+)\s*mbps", com)
			if speed_match:
				speed = int(speed_match.group(1))
				return {
					"verified": True,
					"source": "review",
					"speed_mbps": speed,
					"details": f"Guest review speed test: {speed} Mbps",
				}
			if (
				"fibra" in com
				or ("zoom" in com and "sin problema" in com)
				or "flawless wifi" in com
			):
				return {
					"verified": True,
					"source": "review",
					"speed_mbps": None,
					"details": "Guest review verified remote work / fiber",
				}

		return {
			"verified": False,
			"source": "none",
			"speed_mbps": None,
			"details": "Standard wifi",
		}

	def extract_review_evidence(self, listing):
		"""
		Extracts verified review evidence (quotes) for remote work, wifi, noise, kitchen, and cleanliness issues.
		"""
		reviews = listing.get("reviews", [])
		wifi_pos = []
		wifi_neg = []
		noise_pos = []
		noise_neg = []
		kitchen_pos = []
		kitchen_neg = []
		cleanliness_neg = []

		wifi_pos_weights = []
		wifi_neg_weights = []
		noise_pos_weights = []
		noise_neg_weights = []

		wifi_pos_regex = re.compile(
			r"\b(wifi|wi-fi|internet|fibra|fiber|speed|mbps|zoom|teams|videocall|videollamada)\b",
			re.IGNORECASE,
		)
		wifi_neg_regex = re.compile(
			r"\b(slow wifi|bad wifi|wifi lento|sin internet|internet se cortaba|inestable|poor wifi)\b",
			re.IGNORECASE,
		)
		noise_pos_regex = re.compile(
			r"\b(tranquil[oa]|silencios[oa]|quiet|peaceful|dormir bien|sin ruido)\b",
			re.IGNORECASE,
		)
		noise_neg_regex = re.compile(
			r"\b(ruidos[oa]|mucho ruido|ruido|bulla|tr[aá]fico|loud|noisy|street noise|fiesta|party|construcci[oó]n|obras)\b",
			re.IGNORECASE,
		)
		kitchen_pos_regex = re.compile(
			r"\b(cocinar|cozinhar|cocina completa|bien equipada|horno|oven|cook)\b",
			re.IGNORECASE,
		)
		kitchen_neg_regex = re.compile(
			r"\b(cocina b[aá]sica|sin horno|no oven|lo m[ií]nimo|little equipment)\b",
			re.IGNORECASE,
		)
		cleanliness_neg_regex = re.compile(
			r"\b(cucaracha|roach|bug|insecto|humedad|mold|mal olor|dirty|sucio)\b",
			re.IGNORECASE,
		)

		for r in reviews:
			com = (r.get("comments") or "").replace("\n", " ").strip()
			if not com:
				continue
			w, _ = self._parse_review_recency_weight(r)
			if wifi_neg_regex.search(com):
				wifi_neg.append(com)
				wifi_neg_weights.append(w)
			elif wifi_pos_regex.search(com):
				wifi_pos.append(com)
				wifi_pos_weights.append(w)

			if noise_neg_regex.search(com):
				noise_neg.append(com)
				noise_neg_weights.append(w)
			elif noise_pos_regex.search(com):
				noise_pos.append(com)
				noise_pos_weights.append(w)

			if kitchen_neg_regex.search(com):
				kitchen_neg.append(com)
			elif kitchen_pos_regex.search(com):
				kitchen_pos.append(com)

			if cleanliness_neg_regex.search(com):
				cleanliness_neg.append(com)

		# Resolution supersession logic:
		# 1. Wi-Fi: If negative wifi reviews are historical (weights <= 0.5) and there is a recent positive confirmation
		# or verified fast wifi / fiber in description/title, supersede old complaints.
		has_recent_wifi_pos = any(w >= 1.0 for w in wifi_pos_weights)
		has_fiber_or_speed = bool(
			re.search(
				r"\b(fibra|fiber|1000mbps|\d{2,}\s*mbps)\b",
				f"{listing.get('description', '')} {listing.get('title', '')}",
				re.IGNORECASE,
			)
		)
		if wifi_neg and (has_recent_wifi_pos or has_fiber_or_speed):
			if all(w <= 0.5 for w in wifi_neg_weights):
				logger.info(
					"  Superseded historical Wi-Fi complaints due to recent speed confirmation."
				)
				wifi_neg = []

		# 2. Noise: If negative noise reviews are ancient (weights <= 0.2) and there are 2+ recent quiet reviews
		has_recent_quiet = sum(1 for w in noise_pos_weights if w >= 1.0) >= 2
		if noise_neg and has_recent_quiet:
			if all(w <= 0.2 for w in noise_neg_weights):
				logger.info(
					"  Superseded ancient noise complaint due to recent quiet reviews."
				)
				noise_neg = []

		return {
			"wifi_positive": wifi_pos[:3],
			"wifi_negative": wifi_neg[:2],
			"noise_positive": noise_pos[:3],
			"noise_negative": noise_neg[:2],
			"kitchen_positive": kitchen_pos[:3],
			"kitchen_negative": kitchen_neg[:2],
			"cleanliness_negative": cleanliness_neg[:2],
		}
