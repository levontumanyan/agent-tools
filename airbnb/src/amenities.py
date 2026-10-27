"""Canonical Amenity Registry and Multi-Layer Kitchen & Living Evaluation Module."""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("airbnb")

AMENITY_REGISTRY: Dict[str, Dict[str, Any]] = {
	"ac": {
		"search_id": 5,
		"titles": [
			"air conditioning",
			"central air conditioning",
			"portable air conditioning",
			"split-type ductless ac",
			"split type ductless ac",
			"window ac unit",
			"aire acondicionado",
			"a/c",
			"minisplit",
			"mini-split",
			"split",
			"climatizador",
			"climatiseur",
			"ar condicionado",
		],
		"icons": ["SYSTEM_SNOWFLAKE"],
		"name": "Air Conditioning",
	},
	"air_conditioning": {
		"search_id": 5,
		"alias_of": "ac",
	},
	"kitchen": {
		"search_id": 8,
		"titles": ["kitchen", "cocina"],
		"icons": ["SYSTEM_COOKING_BASICS"],
		"name": "Kitchen",
	},
	"stove": {
		"search_id": None,
		"titles": [
			"stove",
			"gas stove",
			"electric stove",
			"induction stove",
			"cocina a gas",
			"cocina electrica",
			"cocina eléctrica",
			"estufa",
			"anafe",
			"anafe electrico",
			"anafe eléctrico",
			"hornalla",
			"hornallas",
			"parrilla",
			"parrilla de gas",
			"vitroceramica",
			"vitrocerámica",
			"vitro",
			"placa de induccion",
			"placa de inducción",
			"fogao",
			"fogão",
			"cooktop",
		],
		"icons": ["SYSTEM_STOVE"],
		"name": "Stove",
	},
	"oven": {
		"search_id": None,
		"titles": [
			"oven",
			"baking oven",
			"gas oven",
			"electric oven",
			"horno",
			"horno a gas",
			"horno electrico",
			"horno eléctrico",
			"horno convencional",
		],
		"exclude_substrings": ["microondas", "microwave"],
		"icons": ["SYSTEM_OVEN"],
		"name": "Oven",
	},
	"refrigerator": {
		"search_id": None,
		"titles": [
			"refrigerator",
			"fridge",
			"full-size refrigerator",
			"mini fridge",
			"refrigerador",
			"refrigeradora",
			"heladera",
			"heladera con freezer",
			"nevera",
			"frigobar",
			"geladeira",
		],
		"icons": ["SYSTEM_REFRIGERATOR"],
		"name": "Refrigerator",
	},
	"cooking_basics": {
		"search_id": None,
		"titles": [
			"cooking basics",
			"pots and pans",
			"ollas y sartenes",
			"elementos basicos para cocinar",
			"elementos básicos para cocinar",
		],
		"icons": ["SYSTEM_COOKING_BASICS"],
		"name": "Cooking Basics",
	},
	"dishwasher": {
		"search_id": None,
		"titles": ["dishwasher", "lavavajillas", "lava-louças"],
		"icons": ["SYSTEM_DISHWASHER"],
		"name": "Dishwasher",
	},
	"washer": {
		"search_id": 33,
		"titles": [
			"washer",
			"free washer – in unit",
			"free washer - in unit",
			"lavadora",
			"máquina de lavar",
			"maquina de lavar",
		],
		"icons": ["SYSTEM_WASHER"],
		"name": "Washer",
	},
	"dryer": {
		"search_id": 34,
		"titles": [
			"dryer",
			"free dryer – in unit",
			"free dryer - in unit",
			"secadora",
			"secadora de ropa",
		],
		"icons": ["SYSTEM_DRYER"],
		"name": "Dryer",
	},
	"dedicated_workspace": {
		"search_id": 47,
		"titles": [
			"dedicated workspace",
			"workspace",
			"desk",
			"zona de trabajo",
			"espacio de trabajo",
			"espacio de trabajo exclusivo",
			"mesa de trabajo",
			"mesa para laptop",
			"escritorio",
		],
		"icons": ["SYSTEM_DESK", "SYSTEM_OFFICE", "SYSTEM_WORKSPACE"],
		"name": "Dedicated Workspace",
	},
	"wifi": {
		"search_id": 4,
		"titles": ["wifi", "wi-fi", "wireless internet", "fast wifi", "internet"],
		"icons": ["SYSTEM_WI_FI"],
		"name": "Wi-Fi",
	},
	"heating": {
		"search_id": 30,
		"titles": ["heating", "calefaccion", "calefacción", "aquecedor"],
		"icons": ["SYSTEM_THERMOMETER"],
		"name": "Heating",
	},
	"pool": {
		"search_id": 7,
		"titles": ["pool", "piscina", "swimming pool"],
		"icons": ["SYSTEM_POOL"],
		"name": "Pool",
	},
	"gym": {
		"search_id": 15,
		"titles": ["gym", "fitness center", "gimnasio", "academia"],
		"icons": ["SYSTEM_GYM"],
		"name": "Gym",
	},
	"elevator": {
		"search_id": 21,
		"titles": ["elevator", "ascensor", "elevador"],
		"icons": ["SYSTEM_ELEVATOR"],
		"name": "Elevator",
	},
}

DESCRIPTION_FALLBACK_PATTERNS = {
	"stove": re.compile(
		r"\b(estufa|cooktop|anafe|hornalla|hornallas|parrilla\s+de\s+gas|vitrocer[aá]mica|fog[aã]o|gas\s+stove|electric\s+stove|induction\s+stove)\b",
		re.IGNORECASE,
	),
	"oven": re.compile(
		r"(?<!microondas\s)(?<!microwave\s)\b(horno\s+(?:a\s+gas|el[eé]ctrico|convencional|para\s+hornear)|baking\s+oven|gas\s+oven|electric\s+oven)\b(?!\s*microondas)(?!\s*microwave)",
		re.IGNORECASE,
	),
	"refrigerator": re.compile(
		r"\b(refrigerador[a]?|refrigerator|fridge|heladera|nevera|geladeira|frigobar)\b",
		re.IGNORECASE,
	),
	"dedicated_workspace": re.compile(
		r"\b(escritorio|dedicated\s+desk|workspace|zona\s+de\s+trabajo|espacio\s+de\s+trabajo|mesa\s+de\s+trabajo|silla\s+(?:ergon[oó]mica|de\s+oficina)|office\s+chair)\b",
		re.IGNORECASE,
	),
	"ac": re.compile(
		r"(?<!sin\s)(?<!no\s)\b(aire\s+acondicionado|air\s+conditioning|a/c|minisplit|mini-split|climatizador|ar\s+condicionado)\b",
		re.IGNORECASE,
	),
	"washer": re.compile(
		r"(?<!sin\s)(?<!laundromat\s)\b(lavadora|washing\s+machine|washer)\b",
		re.IGNORECASE,
	),
	"heating": re.compile(
		r"(?<!sin\s)(?<!no\s)\b(calefacci[oó]n|calefactor|radiador|aquecedor|chimenea|estufa\s+a\s+le[nñ]a|heater|heating)\b",
		re.IGNORECASE,
	),
}


def get_search_id(slug: str) -> Optional[int]:
	"""Returns the Airbnb search filter ID for a canonical amenity slug."""
	norm_slug = slug.strip().lower()
	entry = AMENITY_REGISTRY.get(norm_slug)
	if not entry:
		return None
	if "alias_of" in entry:
		entry = AMENITY_REGISTRY.get(entry["alias_of"], {})
	return entry.get("search_id")


def extract_available_amenities(
	listing_details: Dict[str, Any],
) -> List[Dict[str, str]]:
	"""
	Extracts all available amenities from the listing's categorized amenity blocks.
	Filters out items where 'available' is explicitly False.
	"""
	available = []
	categories = listing_details.get("amenities") or []
	for category in categories:
		if not isinstance(category, dict):
			continue
		values = category.get("values") or []
		for item in values:
			if not isinstance(item, dict):
				continue
			if item.get("available") is False:
				continue
			title = (item.get("title") or item.get("name") or "").strip().lower()
			icon = (item.get("icon") or "").strip()
			if title or icon:
				available.append({"title": title, "icon": icon})
	return available


def has_amenity(
	listing_details: Dict[str, Any], slug_or_title: str, check_description: bool = True
) -> bool:
	"""
	Checks whether the listing provides an amenity matching the given slug or title.
	Multi-layer:
	1. Structured amenity checkboxes & system icons (with false-positive exclusion for microwaves).
	2. Description text regex inspection fallback.
	"""
	if not slug_or_title:
		return False

	available = extract_available_amenities(listing_details)
	norm_query = slug_or_title.strip().lower()
	entry = AMENITY_REGISTRY.get(norm_query)
	if entry and "alias_of" in entry:
		entry = AMENITY_REGISTRY.get(entry["alias_of"])

	if entry:
		target_titles = [t.lower() for t in entry.get("titles", [])]
		target_icons = set(entry.get("icons", []))
		exclude_substrings = entry.get("exclude_substrings", [])

		for item in available:
			item_title = item["title"]
			item_icon = item["icon"]

			# Check exclusions (e.g. microwave oven must not match oven)
			if exclude_substrings and any(
				exc in item_title for exc in exclude_substrings
			):
				continue

			if item_icon and item_icon in target_icons:
				return True

			for target in target_titles:
				if len(target) <= 3:
					if re.search(rf"\b{re.escape(target)}\b", item_title):
						return True
				elif target in item_title:
					return True

	# Fallback check on normalized query within structured amenities
	clean_query = norm_query.replace("_", " ")
	for item in available:
		item_title = item["title"]
		# Exclude microwave false positive if querying oven
		if norm_query in ("oven", "horno") and any(
			x in item_title for x in ("microondas", "microwave")
		):
			continue
		if len(clean_query) <= 3:
			if re.search(rf"\b{re.escape(clean_query)}\b", item_title):
				return True
		elif clean_query in item_title or norm_query in item_title:
			return True

	# Layer 2: Host description text regex fallback
	if check_description:
		desc_text = f"{listing_details.get('description', '')} {listing_details.get('title', '')}".lower()
		pat = DESCRIPTION_FALLBACK_PATTERNS.get(norm_query)
		if pat and pat.search(desc_text):
			logger.debug(
				f"  Amenity '{norm_query}' detected via host description regex."
			)
			return True

	return False


def evaluate_kitchen(
	listing_details: Dict[str, Any], review_evidence: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
	"""
	Multi-layer kitchen quality evaluation:
	Layer 1: Structured amenities (Stove, Oven, Refrigerator, Cooking basics, Dishwasher).
	Layer 2: Host description regex (mentions of cooktop, conventional oven, fridge).
	Layer 3: Guest review sentiment verification (cooking praise vs complaints).
	"""
	has_kit = has_amenity(listing_details, "kitchen")
	has_stove = has_amenity(listing_details, "stove")
	has_oven = has_amenity(listing_details, "oven")
	has_fridge = has_amenity(listing_details, "refrigerator")
	has_basics = has_amenity(listing_details, "cooking_basics")
	has_dw = has_amenity(listing_details, "dishwasher")

	equipment = {
		"kitchen": has_kit,
		"stove": has_stove,
		"oven": has_oven,
		"refrigerator": has_fridge,
		"cooking_basics": has_basics,
		"dishwasher": has_dw,
	}

	evidence = review_evidence or {}
	kitchen_neg = evidence.get("kitchen_negative") or []
	kitchen_pos = evidence.get("kitchen_positive") or []
	flags: List[str] = []

	# Review evidence overrides
	review_complains_no_oven = any(
		"sin horno" in com.lower() or "no oven" in com.lower() for com in kitchen_neg
	)
	review_complains_bare_kitchenette = any(
		"cocina básica" in com.lower()
		or "cocina basica" in com.lower()
		or "little equipment" in com.lower()
		or "solo microondas" in com.lower()
		for com in kitchen_neg
	)

	# Full kitchen strictly requires refrigerator + (stove or oven)
	if (
		has_kit
		and (has_stove or has_oven)
		and has_fridge
		and not review_complains_bare_kitchenette
	):
		tier = "full_kitchen"
		if not has_oven or review_complains_no_oven:
			flags.append("[FLAG: No Oven]")
	elif has_kit and (has_stove or has_fridge):
		tier = "standard_kitchen"
		if not has_oven or review_complains_no_oven:
			flags.append("[FLAG: No Oven]")
		if not has_stove:
			flags.append("[FLAG: No Stove]")
		if not has_fridge:
			flags.append("[FLAG: No Refrigerator]")
	elif has_kit:
		tier = "kitchenette"
		flags.append("[FLAG: Kitchenette Only / No Stove or Oven]")
	else:
		tier = "no_kitchen"
		flags.append("[FLAG: No Kitchen]")

	if kitchen_neg:
		flags.append("[FLAG: Kitchen Complaints in Reviews]")
	elif kitchen_pos and tier == "full_kitchen":
		flags.append("[SIGNAL: Verified Cooking Kitchen]")

	return {
		"tier": tier,
		"equipment": equipment,
		"flags": flags,
	}
