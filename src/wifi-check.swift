#!/usr/bin/env swift

import Foundation
import CoreWLAN

// ============================================================================
// wifi-check: Comprehensive macOS Wi-Fi & Internet Diagnostic Utility
// ============================================================================

struct Colors {
	static let reset = "\u{001B}[0m"
	static let bold = "\u{001B}[1m"
	static let dim = "\u{001B}[2m"
	static let green = "\u{001B}[32m"
	static let yellow = "\u{001B}[33m"
	static let red = "\u{001B}[31m"
	static let cyan = "\u{001B}[36m"
	static let blue = "\u{001B}[34m"
}

struct WifiDetails: Codable {
	var interfaceName: String
	var ssid: String?
	var bssid: String?
	var band: String
	var channel: Int
	var channelWidthMHz: Int
	var rssi: Int
	var noise: Int
	var snr: Int
	var txRateMbps: Double
	var phyMode: String
	var signalQuality: String
}

struct DeepDiagnostics: Codable {
	var ccaPercent: Int?
	var ccaRating: String?
	var nssStreams: Int?
	var mcsIndex: Int?
	var guardInterval: String?
	var btcMode: String?
	var desense: String?
	var captivePortalStatus: String?
}

struct IpDetails: Codable {
	var publicIp: String?
	var hostname: String?
	var city: String?
	var region: String?
	var country: String?
	var org: String?
	var localGateway: String?
}

struct PingResult: Codable {
	var host: String
	var packetsSent: Int
	var packetsReceived: Int
	var packetLossPercent: Double
	var minMs: Double
	var avgMs: Double
	var maxMs: Double
	var stddevMs: Double
}

struct SpeedResult: Codable {
	var downloadMbps: Double
	var uploadMbps: Double
	var idleLatencyMs: Double
	var responsivenessRpm: Double
	var loadedLatencyMs: Double?
	var testEndpoint: String
}

struct DnsLatencyResult: Codable {
	var queryDomain: String
	var queryTimeMs: Double
	var server: String
}

struct VpnAuditResult: Codable {
	var isVpnDetected: Bool
	var tunnelName: String
	var homeIpMatch: Bool
	var dnsResolverGeo: String?
	var ednsClientGeo: String?
	var isDnsSecure: Bool
	var ipv6Status: String
}

struct HopResult: Codable {
	var hopNumber: Int
	var ip: String
	var rttMs: Double
	var deltaMs: Double?
	var stageDescription: String
}

struct DiagnosticReport: Codable {
	var timestamp: String
	var wifi: WifiDetails?
	var deep: DeepDiagnostics?
	var ip: IpDetails?
	var vpn: VpnAuditResult?
	var hops: [HopResult]
	var ping: [PingResult]
	var dnsLatency: DnsLatencyResult?
	var speed: SpeedResult?
	var jitterRating: String?
	var nomadRating: String
}

func printUsage() {
	let usage = """
	wifi-check: Complete macOS Wi-Fi, VPN stealth, and network performance diagnostic

	Usage:
	  wifi-check [options]

	Features:
	  • Wi-Fi Link Health: RSSI, SNR, MIMO streams, transmit link rate, and channel width
	  • VPN & Stealth Audit: Validates home residential IP, tests for DNS leaks, and checks IPv6
	  • Latency Route Map: Hop-by-hop breakdown (Local Airwaves ➔ Subsea Tunnel ➔ Home LAN ➔ Edge)
	  • Internet Capacity: Download/upload bandwidth and loaded bufferbloat responsiveness (RPM)

	Options:
	  -q, --quick        Quick mode (skip ~15s throughput test; runs Wi-Fi + VPN + hops + ping)
	  -d, --deep         Deep hardware mode (reads airtime congestion, MIMO streams, MCS via sudo wdutil)
	  -s, --scan         Scan and display nearby Wi-Fi networks and signal strengths
	  -j, --json         Output raw JSON for automation, logging, or Grafana dashboards
	  -c, --count <N>    Number of ping probe packets (default: 5)
	  -h, --help         Show this help message
	"""
	print(usage)
}

func getSignalQuality(rssi: Int) -> (rating: String, color: String) {
	switch rssi {
	case -55 ... 0:
		return ("Excellent", Colors.green)
	case -67 ... -56:
		return ("Very Good", Colors.green)
	case -75 ... -68:
		return ("Fair / Usable", Colors.yellow)
	case -85 ... -76:
		return ("Weak", Colors.yellow)
	default:
		return ("Poor / Unstable", Colors.red)
	}
}

func getPhyModeName(_ mode: CWPHYMode) -> String {
	switch mode {
	case .modeNone: return "Unknown"
	case .mode11a: return "802.11a (Wi-Fi 1)"
	case .mode11b: return "802.11b (Wi-Fi 2)"
	case .mode11g: return "802.11g (Wi-Fi 3)"
	case .mode11n: return "802.11n (Wi-Fi 4)"
	case .mode11ac: return "802.11ac (Wi-Fi 5)"
	case .mode11ax: return "802.11ax (Wi-Fi 6)"
	case .mode11be: return "802.11be (Wi-Fi 7)"
	@unknown default: return "Unknown"
	}
}

func getChannelWidthMHz(_ width: CWChannelWidth) -> Int {
	switch width {
	case .width20MHz: return 20
	case .width40MHz: return 40
	case .width80MHz: return 80
	case .width160MHz: return 160
	default: return 20
	}
}

func inspectCurrentWifi() -> WifiDetails? {
	guard let iface = CWWiFiClient.shared().interface() else {
		return nil
	}
	let ch = iface.wlanChannel()
	let bandStr: String
	switch ch?.channelBand {
	case .band2GHz: bandStr = "2.4 GHz"
	case .band5GHz: bandStr = "5 GHz"
	case .band6GHz: bandStr = "6 GHz"
	default: bandStr = "Unknown"
	}

	let rssi = iface.rssiValue()
	let noise = iface.noiseMeasurement()
	let snr = rssi - noise
	let (quality, _) = getSignalQuality(rssi: rssi)

	return WifiDetails(
		interfaceName: iface.interfaceName ?? "en0",
		ssid: iface.ssid(),
		bssid: iface.bssid(),
		band: bandStr,
		channel: Int(ch?.channelNumber ?? 0),
		channelWidthMHz: getChannelWidthMHz(ch?.channelWidth ?? .widthUnknown),
		rssi: rssi,
		noise: noise,
		snr: snr,
		txRateMbps: iface.transmitRate(),
		phyMode: getPhyModeName(iface.activePHYMode()),
		signalQuality: quality
	)
}

func runDeepDiagnostics() -> DeepDiagnostics? {
	let pipe = Pipe()
	let process = Process()
	process.executableURL = URL(fileURLWithPath: "/usr/bin/sudo")
	process.arguments = ["wdutil", "info"]
	process.standardOutput = pipe

	do {
		try process.run()
		process.waitUntilExit()
	} catch {
		return nil
	}

	guard process.terminationStatus == 0 else { return nil }

	let data = pipe.fileHandleForReading.readDataToEndOfFile()
	guard let output = String(data: data, encoding: .utf8) else { return nil }

	var diag = DeepDiagnostics()

	for line in output.split(separator: "\n") {
		let lineStr = String(line)
		let parts = lineStr.split(separator: ":", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
		if parts.count == 2 {
			let key = parts[0]
			let val = parts[1]

			if key == "CCA" {
				if let num = Int(val.replacingOccurrences(of: "%", with: "").trimmingCharacters(in: .whitespaces)) {
					diag.ccaPercent = num
					if num < 25 {
						diag.ccaRating = "Clean (< 25% Airtime Contention)"
					} else if num < 50 {
						diag.ccaRating = "Moderate (25-50% Airtime Contention)"
					} else {
						diag.ccaRating = "Heavy Congestion (> 50% Airtime Busy)"
					}
				}
			} else if key == "NSS" {
				if let num = Int(val) {
					diag.nssStreams = num
				}
			} else if key == "MCS Index" {
				if let num = Int(val) {
					diag.mcsIndex = num
				}
			} else if key == "Guard Interval" {
				diag.guardInterval = val.contains("400") ? "400 ns (Short / Fast)" : "\(val) ns"
			} else if key == "BTC Mode" {
				diag.btcMode = val
			} else if key == "Desense" && !val.isEmpty {
				diag.desense = val
			} else if key == "Apple" {
				diag.captivePortalStatus = val
			}
		}
	}

	return diag
}

func scanNearbyNetworks() -> [WifiDetails] {
	guard let iface = CWWiFiClient.shared().interface() else { return [] }
	let scan = (try? iface.scanForNetworks(withName: nil)) ?? []
	var results: [WifiDetails] = []

	for net in scan {
		let ch = net.wlanChannel
		let bandStr: String
		switch ch?.channelBand {
		case .band2GHz: bandStr = "2.4 GHz"
		case .band5GHz: bandStr = "5 GHz"
		case .band6GHz: bandStr = "6 GHz"
		default: bandStr = "Unknown"
		}
		let rssi = net.rssiValue
		let noise = net.noiseMeasurement
		let (quality, _) = getSignalQuality(rssi: rssi)

		results.append(WifiDetails(
			interfaceName: iface.interfaceName ?? "en0",
			ssid: net.ssid ?? "(Hidden)",
			bssid: net.bssid,
			band: bandStr,
			channel: Int(ch?.channelNumber ?? 0),
			channelWidthMHz: getChannelWidthMHz(ch?.channelWidth ?? .widthUnknown),
			rssi: rssi,
			noise: noise,
			snr: rssi - noise,
			txRateMbps: 0,
			phyMode: "",
			signalQuality: quality
		))
	}
	return results.sorted { $0.rssi > $1.rssi }
}

func getLocalGateway() -> String? {
	let pipe = Pipe()
	let netstat = Process()
	netstat.executableURL = URL(fileURLWithPath: "/usr/sbin/netstat")
	netstat.arguments = ["-nr"]
	netstat.standardOutput = pipe
	try? netstat.run()
	netstat.waitUntilExit()

	let data = pipe.fileHandleForReading.readDataToEndOfFile()
	guard let output = String(data: data, encoding: .utf8) else { return nil }
	for line in output.split(separator: "\n") {
		let parts = line.split(whereSeparator: { $0.isWhitespace })
		if parts.count >= 2 && parts[0] == "default" {
			let gw = String(parts[1])
			if !gw.contains(":") {
				return gw
			}
		}
	}
	return nil
}

func fetchPublicIpDetails(gateway: String?) -> IpDetails {
	var details = IpDetails()
	details.localGateway = gateway

	let curlPipe = Pipe()
	let curl = Process()
	curl.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
	curl.arguments = ["-s", "--connect-timeout", "3", "--max-time", "5", "https://ipinfo.io/json"]
	curl.standardOutput = curlPipe
	try? curl.run()
	curl.waitUntilExit()

	let curlData = curlPipe.fileHandleForReading.readDataToEndOfFile()
	if let json = try? JSONSerialization.jsonObject(with: curlData) as? [String: Any] {
		details.publicIp = json["ip"] as? String
		details.hostname = json["hostname"] as? String
		details.city = json["city"] as? String
		details.region = json["region"] as? String
		details.country = json["country"] as? String
		details.org = json["org"] as? String
	}

	return details
}

func fetchEdnsGeo() -> (dnsGeo: String?, ednsGeo: String?) {
	let curlPipe = Pipe()
	let curl = Process()
	curl.executableURL = URL(fileURLWithPath: "/usr/bin/curl")
	curl.arguments = ["-sL", "--connect-timeout", "2", "--max-time", "3", "https://edns.ip-api.com/json"]
	curl.standardOutput = curlPipe
	try? curl.run()
	curl.waitUntilExit()

	let data = curlPipe.fileHandleForReading.readDataToEndOfFile()
	var dnsGeo: String? = nil
	var ednsGeo: String? = nil
	if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
		if let dns = json["dns"] as? [String: Any], let geo = dns["geo"] as? String {
			dnsGeo = geo
		}
		if let edns = json["edns"] as? [String: Any], let geo = edns["geo"] as? String {
			ednsGeo = geo
		}
	}
	return (dnsGeo, ednsGeo)
}

func checkIPv6Status() -> String {
	var ipv6Status = "Disabled on en0 (Protected)"
	let ifPipe = Pipe()
	let ifProc = Process()
	ifProc.executableURL = URL(fileURLWithPath: "/sbin/ifconfig")
	ifProc.arguments = ["en0"]
	ifProc.standardOutput = ifPipe
	try? ifProc.run()
	ifProc.waitUntilExit()

	let ifData = ifPipe.fileHandleForReading.readDataToEndOfFile()
	if let ifStr = String(data: ifData, encoding: .utf8) {
		for line in ifStr.split(separator: "\n") {
			let lineTrimmed = line.trimmingCharacters(in: .whitespaces)
			if lineTrimmed.hasPrefix("inet6 ") {
				let parts = lineTrimmed.split(separator: " ")
				if parts.count >= 2 {
					let addr = String(parts[1])
					if !addr.hasPrefix("fe80:") {
						ipv6Status = "Active Routable IPv6 (\(addr.prefix(16))...) - Potential Leak"
						break
					}
				}
			}
		}
	}
	return ipv6Status
}

func measureDnsLatency(domain: String = "google.com") -> DnsLatencyResult? {
	let pipe = Pipe()
	let proc = Process()
	proc.executableURL = URL(fileURLWithPath: "/usr/bin/dig")
	proc.arguments = ["+stats", "+time=2", "+tries=1", domain]
	proc.standardOutput = pipe
	try? proc.run()
	proc.waitUntilExit()

	let data = pipe.fileHandleForReading.readDataToEndOfFile()
	guard let output = String(data: data, encoding: .utf8) else { return nil }

	var queryMs: Double? = nil
	var server: String = "System Resolver"

	for line in output.split(separator: "\n") {
		let lineStr = String(line)
		if lineStr.contains("Query time:") {
			let parts = lineStr.split(separator: ":")
			if parts.count >= 2 {
				let timePart = parts[1].trimmingCharacters(in: .whitespaces).replacingOccurrences(of: " msec", with: "")
				queryMs = Double(timePart)
			}
		} else if lineStr.contains("SERVER:") {
			let parts = lineStr.split(separator: ":")
			if parts.count >= 2 {
				let srvPart = parts[1].trimmingCharacters(in: .whitespaces).split(separator: "(").first ?? ""
				let srvStr = srvPart.trimmingCharacters(in: .whitespaces).components(separatedBy: "#").first ?? ""
				if !srvStr.isEmpty {
					server = srvStr
				}
			}
		}
	}

	if let ms = queryMs {
		return DnsLatencyResult(queryDomain: domain, queryTimeMs: ms, server: server)
	}
	return nil
}

func runPingTest(host: String, count: Int = 5) -> PingResult? {
	let pipe = Pipe()
	let process = Process()
	process.executableURL = URL(fileURLWithPath: "/sbin/ping")
	process.arguments = ["-c", "\(count)", host]
	process.standardOutput = pipe
	try? process.run()
	process.waitUntilExit()

	let data = pipe.fileHandleForReading.readDataToEndOfFile()
	guard let output = String(data: data, encoding: .utf8) else { return nil }

	var sent = count
	var received = 0
	var loss = 100.0
	var minMs = 0.0
	var avgMs = 0.0
	var maxMs = 0.0
	var stddevMs = 0.0

	for line in output.split(separator: "\n") {
		let lineStr = String(line)
		if lineStr.contains("packets transmitted") {
			let components = lineStr.split(separator: ",")
			for comp in components {
				if comp.contains("packets transmitted"), let num = Int(comp.trimmingCharacters(in: .whitespaces).split(separator: " ").first ?? "") {
					sent = num
				}
				if comp.contains("packets received"), let num = Int(comp.trimmingCharacters(in: .whitespaces).split(separator: " ").first ?? "") {
					received = num
				}
				if comp.contains("% packet loss"), let numStr = comp.trimmingCharacters(in: .whitespaces).split(separator: "%").first?.split(separator: " ").last, let num = Double(numStr) {
					loss = num
				}
			}
		}
		if lineStr.contains("min/avg/max") {
			if let statsPart = lineStr.split(separator: "=").last {
				let parts = statsPart.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: " ms", with: "").split(separator: "/")
				if parts.count == 4 {
					minMs = Double(parts[0]) ?? 0
					avgMs = Double(parts[1]) ?? 0
					maxMs = Double(parts[2]) ?? 0
					stddevMs = Double(parts[3]) ?? 0
				}
			}
		}
	}

	return PingResult(
		host: host,
		packetsSent: sent,
		packetsReceived: received,
		packetLossPercent: loss,
		minMs: minMs,
		avgMs: avgMs,
		maxMs: maxMs,
		stddevMs: stddevMs
	)
}

func runSpeedTest() -> SpeedResult? {
	let pipe = Pipe()
	let process = Process()
	process.executableURL = URL(fileURLWithPath: "/usr/bin/networkQuality")
	process.arguments = ["-c"]
	process.standardOutput = pipe
	try? process.run()
	process.waitUntilExit()

	let data = pipe.fileHandleForReading.readDataToEndOfFile()
	guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }

	let dlThroughput = (json["dl_throughput"] as? Double) ?? 0.0
	let ulThroughput = (json["ul_throughput"] as? Double) ?? 0.0
	let idleLatency = (json["idle_latency"] as? Double) ?? (json["base_rtt"] as? Double) ?? 0.0
	let responsiveness = (json["responsiveness"] as? Double) ?? 0.0
	let endpoint = (json["test_endpoint"] as? String) ?? "Apple Edge"

	// Throughput is reported in bits per second by networkQuality -c
	let dlMbps = (dlThroughput / 1_000_000.0)
	let ulMbps = (ulThroughput / 1_000_000.0)
	let loadedMs = responsiveness > 0 ? (60_000.0 / responsiveness) : nil

	return SpeedResult(
		downloadMbps: (dlMbps * 10).rounded() / 10,
		uploadMbps: (ulMbps * 10).rounded() / 10,
		idleLatencyMs: (idleLatency * 10).rounded() / 10,
		responsivenessRpm: responsiveness,
		loadedLatencyMs: loadedMs != nil ? ((loadedMs! * 10).rounded() / 10) : nil,
		testEndpoint: endpoint
	)
}

func auditVpnAndDns(ip: IpDetails, dnsGeo: String?, ednsGeo: String?, ipv6Status: String) -> VpnAuditResult {
	let isBeryl = ip.localGateway == "192.168.8.1"
	let isHomeRogers = ip.publicIp == "99.241.213.21" || (ip.org?.contains("Rogers") ?? false)
	let isVpn = isBeryl || isHomeRogers

	let tunnelName: String
	if isHomeRogers {
		tunnelName = "WireGuard Tunnel to Toronto Home (Rogers)"
	} else if isVpn {
		tunnelName = "Active VPN Tunnel"
	} else {
		tunnelName = "None (Direct ISP Connection)"
	}

	var isDnsSecure = true
	if let dns = dnsGeo {
		if isHomeRogers && !dns.contains("Canada") && !dns.contains("United States") {
			isDnsSecure = false
		}
	}

	return VpnAuditResult(
		isVpnDetected: isVpn,
		tunnelName: tunnelName,
		homeIpMatch: isHomeRogers,
		dnsResolverGeo: dnsGeo,
		ednsClientGeo: ednsGeo,
		isDnsSecure: isDnsSecure,
		ipv6Status: ipv6Status
	)
}

func pad(_ str: String, to len: Int) -> String {
	if str.count >= len { return str }
	return str + String(repeating: " ", count: len - str.count)
}

func mapLatencyHops(gateway: String?, isVpn: Bool) -> [HopResult] {
	let pipe = Pipe()
	let errPipe = Pipe()
	let proc = Process()
	proc.executableURL = URL(fileURLWithPath: "/usr/sbin/traceroute")
	proc.arguments = ["-I", "-n", "-m", "8", "-q", "3", "-w", "1", "1.1.1.1"]
	proc.standardOutput = pipe
	proc.standardError = errPipe
	try? proc.run()
	proc.waitUntilExit()

	var data = pipe.fileHandleForReading.readDataToEndOfFile()
	if proc.terminationStatus != 0 || data.isEmpty {
		let fallbackPipe = Pipe()
		let fallbackProc = Process()
		fallbackProc.executableURL = URL(fileURLWithPath: "/usr/sbin/traceroute")
		fallbackProc.arguments = ["-n", "-m", "8", "-q", "3", "-w", "1", "1.1.1.1"]
		fallbackProc.standardOutput = fallbackPipe
		try? fallbackProc.run()
		fallbackProc.waitUntilExit()
		data = fallbackPipe.fileHandleForReading.readDataToEndOfFile()
	}

	guard let output = String(data: data, encoding: .utf8) else { return [] }

	var results: [HopResult] = []
	var prevRtt: Double = 0.0

	for line in output.split(separator: "\n") {
		let parts = line.split(whereSeparator: { $0.isWhitespace })
		if parts.count >= 3, let hopNum = Int(parts[0]) {
			let ip = String(parts[1])
			if ip != "*" {
				var probeTimes: [Double] = []
				var idx = 2
				while idx < parts.count {
					if idx + 1 < parts.count && parts[idx + 1] == "ms" {
						if let t = Double(parts[idx]) {
							probeTimes.append(t)
						}
						idx += 2
					} else {
						idx += 1
					}
				}

				let rtt: Double
				if !probeTimes.isEmpty {
					rtt = probeTimes.min()!
				} else if let fallback = Double(parts[2]) {
					rtt = fallback
				} else {
					continue
				}

				let delta = max(0.0, rtt - prevRtt)
				prevRtt = rtt

				let desc: String
				if hopNum == 1 {
					if ip == "192.168.8.1" {
						desc = "Local Airwaves (Mac ➔ Beryl AX Wi-Fi 6)"
					} else {
						desc = "Local Airwaves (Device ➔ Local Wi-Fi Router)"
					}
				} else if (isVpn || ip == "192.168.89.1") && ip == "192.168.89.1" {
					desc = "Subsea Optical Cable (Tunnel to Toronto ER605)"
				} else if (isVpn || ip == "10.0.0.1") && ip == "10.0.0.1" {
					desc = "Home LAN (ER605 ➔ Rogers Ignite Modem)"
				} else if (isVpn || ip.hasPrefix("99.241.") || ip.hasPrefix("24.156.")) && (ip.hasPrefix("99.241.") || ip.hasPrefix("24.156.")) {
					desc = "Rogers Last Mile / Regional Node (Toronto)"
				} else if isVpn && hopNum >= 6 {
					desc = "Internet Exchange / Cloudflare Peering"
				} else {
					if hopNum == 2 {
						desc = "ISP Central Office / Last Mile (GPON/Fiber)"
					} else if hopNum == 3 {
						desc = "Regional Internet Exchange (Domestic IXP)"
					} else if hopNum == 4 {
						desc = "International Submarine Cable (Long Haul)"
					} else {
						desc = "Transit Backbone / Internet Edge"
					}
				}

				results.append(HopResult(
					hopNumber: hopNum,
					ip: ip,
					rttMs: (rtt * 10).rounded() / 10,
					deltaMs: (delta * 10).rounded() / 10,
					stageDescription: desc
				))
			}
		}
	}
	return results
}

func evaluateJitterRating(pings: [PingResult], gateway: String?) -> (rating: String, isPristine: Bool) {
	let wanPings = pings.filter { $0.host != gateway }
	let localPing = pings.first { $0.host == gateway }

	let maxWanJitter = wanPings.map { $0.stddevMs }.max() ?? 0.0
	let localJitter = localPing?.stddevMs ?? 0.0

	if maxWanJitter < 6.0 && localJitter < 3.0 {
		return ("✅ Pristine VoIP Stability (±\(String(format: "%.1f", localJitter)) ms local, ±\(String(format: "%.1f", maxWanJitter)) ms WAN - Zero stutter)", true)
	} else if maxWanJitter < 15.0 {
		return ("✅ Good Call Stability (±\(String(format: "%.1f", localJitter)) ms local, ±\(String(format: "%.1f", maxWanJitter)) ms WAN - Smooth video/audio)", true)
	} else {
		return ("⚠️ Elevated Jitter (±\(String(format: "%.1f", maxWanJitter)) ms WAN - Packet buffering possible)", false)
	}
}

func evaluateNomadRating(wifi: WifiDetails?, deep: DeepDiagnostics?, ping: PingResult?, speed: SpeedResult?, vpn: VpnAuditResult?) -> String {
	let loss = ping?.packetLossPercent ?? 0.0
	let avgLatency = ping?.avgMs ?? 0.0
	let upload = speed?.uploadMbps ?? 0.0
	let cca = deep?.ccaPercent ?? 0
	let isVpn = vpn?.isVpnDetected ?? false

	if loss > 5.0 {
		return "⚠️ Poor (High Packet Loss: \(loss)%)"
	}
	if cca > 50 {
		return "⚠️ Poor Airtime Congestion (CCA: \(cca)%) - Channel is oversaturated"
	}
	let maxAllowedLatency = isVpn ? 220.0 : 180.0
	if avgLatency > maxAllowedLatency {
		return "⚠️ High Latency (>\(Int(maxAllowedLatency))ms) - Conversational delays expected"
	}
	if speed != nil && upload < 2.0 {
		return "⚠️ Low Upload (<2 Mbps) - Video calls may degrade"
	}
	if isVpn && !(vpn?.homeIpMatch ?? false) {
		return "⚠️ VPN Alert: Public IP does not match Canadian Homebase"
	}
	if (speed == nil || upload >= 10.0) && loss == 0.0 {
		if isVpn {
			return "✅ Optimal for HD Zoom Calls & Remote Work (Protected Canadian Tunnel)"
		} else {
			return "✅ Optimal for HD Zoom Calls & Remote Work"
		}
	}
	return "✅ Good for Standard Video Calls & Remote Work"
}

// ============================================================================
// Main Execution Flow
// ============================================================================

var isQuick = false
var isDeep = false
var isScan = false
var isJson = false
var pingCount = 5

let args = CommandLine.arguments
var i = 1
while i < args.count {
	let arg = args[i]
	switch arg {
	case "-q", "--quick":
		isQuick = true
	case "-d", "--deep":
		isDeep = true
	case "-s", "--scan":
		isScan = true
	case "-j", "--json":
		isJson = true
	case "-c", "--count":
		if i + 1 < args.count, let n = Int(args[i + 1]) {
			pingCount = n
			i += 1
		}
	case "-h", "--help":
		printUsage()
		exit(0)
	default:
		print("Unknown argument: \(arg)")
		printUsage()
		exit(1)
	}
	i += 1
}

if isScan {
	let networks = scanNearbyNetworks()
	if isJson {
		let encoder = JSONEncoder()
		encoder.outputFormatting = .prettyPrinted
		if let data = try? encoder.encode(networks), let str = String(data: data, encoding: .utf8) {
			print(str)
		}
	} else {
		print("\n\(Colors.bold)Nearby Wi-Fi Networks (\(networks.count) detected):\(Colors.reset)\n")
		print(String(format: "%-26@ %-10@ %-8@ %-12@ %-14@", "SSID", "Band", "Channel", "Signal", "Quality"))
		print(String(repeating: "-", count: 72))
		for net in networks {
			let (_, col) = getSignalQuality(rssi: net.rssi)
			let row = String(format: "%-26@ %-10@ %-8d %-12@ \(col)%-14@\(Colors.reset)",
				String(net.ssid?.prefix(25) ?? "(Hidden)"),
				net.band,
				net.channel,
				"\(net.rssi) dBm",
				net.signalQuality
			)
			print(row)
		}
		print("")
	}
	exit(0)
}

// 1. Gather Wi-Fi Link Details & Local Gateway
let wifi = inspectCurrentWifi()
let gateway = getLocalGateway()
let isBeryl = gateway == "192.168.8.1"

// 2. Run Diagnostics & Network Probes Concurrently
let group = DispatchGroup()
let queue = DispatchQueue.global(qos: .userInitiated)

var deep: DeepDiagnostics? = nil
if isDeep || getuid() == 0 {
	group.enter()
	queue.async {
		deep = runDeepDiagnostics()
		group.leave()
	}
}

var ipDetails = IpDetails()
group.enter()
queue.async {
	ipDetails = fetchPublicIpDetails(gateway: gateway)
	group.leave()
}

var ednsData: (dnsGeo: String?, ednsGeo: String?) = (nil, nil)
group.enter()
queue.async {
	ednsData = fetchEdnsGeo()
	group.leave()
}

var ipv6Status = "Disabled on en0 (Protected)"
group.enter()
queue.async {
	ipv6Status = checkIPv6Status()
	group.leave()
}

var dnsLatency: DnsLatencyResult? = nil
group.enter()
queue.async {
	dnsLatency = measureDnsLatency()
	group.leave()
}

var hops: [HopResult] = []
group.enter()
queue.async {
	hops = mapLatencyHops(gateway: gateway, isVpn: isBeryl)
	group.leave()
}

var pingGw: PingResult? = nil
if let gw = gateway {
	group.enter()
	queue.async {
		pingGw = runPingTest(host: gw, count: min(pingCount, 3))
		group.leave()
	}
}

var pingCloudflare: PingResult? = nil
group.enter()
queue.async {
	pingCloudflare = runPingTest(host: "1.1.1.1", count: pingCount)
	group.leave()
}

var pingGoogle: PingResult? = nil
group.enter()
queue.async {
	pingGoogle = runPingTest(host: "8.8.8.8", count: pingCount)
	group.leave()
}

var pingQuad9: PingResult? = nil
group.enter()
queue.async {
	pingQuad9 = runPingTest(host: "9.9.9.9", count: pingCount)
	group.leave()
}

// Wait for all concurrent network queries to complete
group.wait()

// 3. Assemble Audit & Ping Results
let vpn = auditVpnAndDns(ip: ipDetails, dnsGeo: ednsData.dnsGeo, ednsGeo: ednsData.ednsGeo, ipv6Status: ipv6Status)
let pings: [PingResult] = [pingGw, pingCloudflare, pingGoogle, pingQuad9].compactMap { $0 }

// 4. Run Throughput Speed Test (if not quick mode)
var speed: SpeedResult? = nil
if !isQuick {
	if !isJson {
		print("\(Colors.dim)Testing internet capacity & bufferbloat via Apple Edge... (takes ~15s)\(Colors.reset)")
	}
	speed = runSpeedTest()
}

// 5. Evaluate Work Suitability & Jitter
let jitterResult = evaluateJitterRating(pings: pings, gateway: gateway)
let rating = evaluateNomadRating(wifi: wifi, deep: deep, ping: pingCloudflare, speed: speed, vpn: vpn)

let report = DiagnosticReport(
	timestamp: ISO8601DateFormatter().string(from: Date()),
	wifi: wifi,
	deep: deep,
	ip: ipDetails,
	vpn: vpn,
	hops: hops,
	ping: pings,
	dnsLatency: dnsLatency,
	speed: speed,
	jitterRating: jitterResult.rating,
	nomadRating: rating
)

if isJson {
	let encoder = JSONEncoder()
	encoder.outputFormatting = .prettyPrinted
	if let data = try? encoder.encode(report), let str = String(data: data, encoding: .utf8) {
		print(str)
	}
	exit(0)
}

// Pretty Terminal Display
print("")
print("\(Colors.bold)\(Colors.cyan)=== macOS Wi-Fi & Internet Diagnostic ===\(Colors.reset)")

// Wi-Fi Hardware Section
print("\n\(Colors.bold)Wi-Fi Wireless Link:\(Colors.reset)")
if let w = wifi {
	let (_, sigColor) = getSignalQuality(rssi: w.rssi)
	print("  • Interface:        \(w.interfaceName)")
	print("  • Frequency Band:   \(w.band) (Channel \(w.channel), \(w.channelWidthMHz) MHz width)")
	print("  • Physical Standard: \(w.phyMode)")
	print("  • Link Transmit Rate: \(w.txRateMbps) Mbps")
	print("  • Signal Strength:  \(sigColor)\(w.rssi) dBm (\(w.signalQuality))\(Colors.reset)")
	print("  • Noise / SNR:      \(w.noise) dBm (SNR: \(w.snr) dB)")
} else {
	print("  • Wi-Fi interface not active or not associated.")
}

// Deep Diagnostics Section
if let d = deep {
	print("\n\(Colors.bold)Deep Radio & Hardware Health (wdutil):\(Colors.reset)")
	if let cca = d.ccaPercent, let rating = d.ccaRating {
		let ccaColor = cca < 25 ? Colors.green : (cca < 50 ? Colors.yellow : Colors.red)
		print("  • Airtime Congestion: \(ccaColor)\(cca)% - \(rating)\(Colors.reset)")
	}
	if let nss = d.nssStreams {
		let nssColor = nss >= 2 ? Colors.green : Colors.yellow
		print("  • Spatial Streams:   \(nssColor)\(nss)x\(nss) MIMO (\(nss >= 2 ? "Dual Antenna" : "Single Stream Degraded"))\(Colors.reset)")
	}
	if let mcs = d.mcsIndex {
		print("  • Modulation (MCS):  Index \(mcs) / 11")
	}
	if let gi = d.guardInterval {
		print("  • Guard Interval:    \(gi)")
	}
	if let btc = d.btcMode {
		let btcColor = btc.lowercased().contains("off") ? Colors.green : Colors.yellow
		print("  • Bluetooth Coexist: \(btcColor)\(btc)\(Colors.reset)")
	}
	if let desense = d.desense {
		print("  • \(Colors.red)⚠️ RF Desensitization: \(desense) (USB-C hub or cable noise detected)\(Colors.reset)")
	}
	if let portal = d.captivePortalStatus {
		print("  • Captive Portal:    \(portal)")
	}
} else if isDeep {
	print("\n\(Colors.dim)Deep hardware diagnostics: sudo permission was not granted.\(Colors.reset)")
}

// IP & Route Section
print("\n\(Colors.bold)Routing & Public Presence:\(Colors.reset)")
print("  • Local Gateway:    \(ipDetails.localGateway ?? "Unknown")")
if let pub = ipDetails.publicIp {
	let loc = [ipDetails.city, ipDetails.region, ipDetails.country].compactMap { $0 }.joined(separator: ", ")
	print("  • Public IP:        \(pub)")
	print("  • ISP / Provider:   \(ipDetails.org ?? "Unknown")")
	print("  • Geo Location:     \(loc)")
} else {
	print("  • Public IP lookup failed (no internet or timeout)")
}

// VPN & Stealth Audit Section
if vpn.isVpnDetected {
	print("\n\(Colors.bold)VPN & Stealth Audit:\(Colors.reset)")
	let statusColor = vpn.homeIpMatch ? Colors.green : Colors.yellow
	print("  • Tunnel Status:    \(statusColor)🔒 \(vpn.tunnelName)\(Colors.reset)")
	let matchTag = vpn.homeIpMatch ? "\(Colors.green)[MATCH: Canadian Homebase]\(Colors.reset)" : "\(Colors.yellow)[Unmatched]\(Colors.reset)"
	print("  • Residential IP:   \(matchTag)")
	if let dns = vpn.dnsResolverGeo {
		let dnsCol = vpn.isDnsSecure ? Colors.green : Colors.red
		let leakTag = vpn.isDnsSecure ? "\(Colors.green)[PASS: Protected]\(Colors.reset)" : "\(Colors.red)[LEAK DETECTED]\(Colors.reset)"
		print("  • DNS Resolver:     \(dnsCol)\(dns)\(Colors.reset) \(leakTag)")
	}
	let v6Col = vpn.ipv6Status.contains("Potential Leak") ? Colors.red : Colors.green
	print("  • IPv6 Leak Check:  \(v6Col)\(vpn.ipv6Status)\(Colors.reset)")
}

// Latency Route Mapping Section
if !hops.isEmpty {
	print("\n\(Colors.bold)Latency Route Mapping (Hop-by-Hop Breakdown):\(Colors.reset)")
	print("  " + pad("Hop", to: 10) + pad("Cumulative", to: 14) + pad("Segment Δ", to: 13) + pad("Node IP", to: 18) + "Stage")
	print(String(repeating: "-", count: 82))
	for h in hops {
		let deltaStr = h.deltaMs != nil ? String(format: "+%.1f ms", h.deltaMs!) : "--"
		let rttStr = String(format: "%.1f ms", h.rttMs)
		let hopLabel = "• Hop \(h.hopNumber):"
		print("  " + pad(hopLabel, to: 10) + pad(rttStr, to: 14) + pad(deltaStr, to: 13) + pad(h.ip, to: 18) + h.stageDescription)
	}
}

// DNS Latency Section
if let d = dnsLatency {
	let dnsCol = d.queryTimeMs < 25 ? Colors.green : (d.queryTimeMs < 75 ? Colors.yellow : Colors.red)
	print("\n\(Colors.bold)DNS Resolution Latency:\(Colors.reset)")
	print("  • Resolver Server:  \(d.server)")
	print("  • Query Latency:    \(dnsCol)\(d.queryTimeMs) ms\(Colors.reset) (Lookup for \(d.queryDomain))")
}

// Ping Section
print("\n\(Colors.bold)Latency & Packet Stability (Multi-Target):\(Colors.reset)")
for p in pings {
	let lossColor = p.packetLossPercent == 0 ? Colors.green : Colors.red
	let targetName: String
	switch p.host {
	case "1.1.1.1": targetName = "Cloudflare Edge (1.1.1.1)"
	case "8.8.8.8": targetName = "Google Public DNS (8.8.8.8)"
	case "9.9.9.9": targetName = "Quad9 Anycast (9.9.9.9)"
	default:
		if p.host == gateway {
			targetName = "Local Gateway (\(p.host))"
		} else {
			targetName = p.host
		}
	}
	print("  • Target: \(targetName)")
	print("    - Packet Loss:    \(lossColor)\(p.packetLossPercent)%\(Colors.reset) (\(p.packetsReceived)/\(p.packetsSent) received)")
	print("    - Latency (RTT):  Avg \(p.avgMs) ms (Min: \(p.minMs) ms, Max: \(p.maxMs) ms)")
	print("    - Jitter (StdDev): ±\(p.stddevMs) ms")
}

// Speed Section
if let s = speed {
	print("\n\(Colors.bold)Throughput & Loaded Latency (Bufferbloat):\(Colors.reset)")
	print("  • Download Speed:   \(Colors.green)\(s.downloadMbps) Mbps\(Colors.reset)")
	print("  • Upload Speed:     \(Colors.green)\(s.uploadMbps) Mbps\(Colors.reset)")
	print("  • Idle Latency:     \(s.idleLatencyMs) ms (Tested via \(s.testEndpoint))")
	let loadedStr = s.loadedLatencyMs != nil ? " (~\(s.loadedLatencyMs!) ms loaded latency)" : ""
	print("  • Responsiveness:   \(Int(s.responsivenessRpm)) RPM\(loadedStr)")
} else if isQuick {
	print("\n\(Colors.dim)Throughput test skipped (--quick mode). Run without -q for full speed test.\(Colors.reset)")
}

// Rating Section
print("\n\(Colors.bold)Nomad & Remote Work Verdict:\(Colors.reset)")
print("  • Call Jitter:      \(jitterResult.rating)")
print("  • Work Verdict:     \(rating)\n")
