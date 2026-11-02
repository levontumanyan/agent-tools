#!/usr/bin/env swift

import Foundation
import SQLite3
import Speech
import AVFoundation

// ============================================================================
// call-recordings: CLI to list, inspect, transcribe, and export iPhone call recordings
// Reads directly from Apple Notes SQLite database and audio attachments
// ============================================================================

struct CallRecord {
	let noteId: Int64
	let noteUUID: String
	let title: String
	let createdAt: Date
	let modifiedAt: Date
	let mediaUUID: String?
	let mediaFilename: String?
	var localAudioPath: String?
	var durationSeconds: Double?
	var transcript: String?
}

// MARK: - Paths & Database

let notesBaseDir = ("~/Library/Group Containers/group.com.apple.notes" as NSString).expandingTildeInPath
let notesDBPath = (notesBaseDir as NSString).appendingPathComponent("NoteStore.sqlite")

let cacheDir: String = {
	let path = ("~/.local/share/call-recordings" as NSString).expandingTildeInPath
	try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true, attributes: nil)
	return path
}()
let transcriptDBPath = (cacheDir as NSString).appendingPathComponent("transcripts.sqlite")

func columnText(_ stmt: OpaquePointer?, _ index: Int32) -> String {
	if let ptr = sqlite3_column_text(stmt, index) {
		return String(cString: ptr)
	}
	return ""
}

func columnTextOpt(_ stmt: OpaquePointer?, _ index: Int32) -> String? {
	if let ptr = sqlite3_column_text(stmt, index) {
		let s = String(cString: ptr)
		return s.isEmpty ? nil : s
	}
	return nil
}

func getNotesDB() -> OpaquePointer? {
	guard FileManager.default.fileExists(atPath: notesDBPath) else {
		fputs("Error: Apple Notes database not found at \(notesDBPath)\n", stderr)
		return nil
	}
	var db: OpaquePointer?
	if sqlite3_open_v2(notesDBPath, &db, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
		let errMsg = db != nil ? String(cString: sqlite3_errmsg(db)) : "Unknown error"
		fputs("Error opening Notes database: \(errMsg)\n", stderr)
		return nil
	}
	return db
}

func getTranscriptDB() -> OpaquePointer? {
	var db: OpaquePointer?
	if sqlite3_open(transcriptDBPath, &db) != SQLITE_OK {
		return nil
	}
	let createSQL = """
	CREATE TABLE IF NOT EXISTS transcripts (
		note_id INTEGER PRIMARY KEY,
		note_uuid TEXT,
		media_uuid TEXT,
		title TEXT,
		date_str TEXT,
		duration REAL,
		transcript TEXT,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);
	CREATE INDEX IF NOT EXISTS idx_transcripts_title ON transcripts(title);
	"""
	sqlite3_exec(db, createSQL, nil, nil, nil)
	return db
}

func getCachedTranscript(noteId: Int64) -> String? {
	guard let db = getTranscriptDB() else { return nil }
	defer { sqlite3_close(db) }

	let query = "SELECT transcript FROM transcripts WHERE note_id = ? LIMIT 1;"
	var stmt: OpaquePointer?
	guard sqlite3_prepare_v2(db, query, -1, &stmt, nil) == SQLITE_OK else { return nil }
	defer { sqlite3_finalize(stmt) }

	sqlite3_bind_int64(stmt, 1, noteId)
	if sqlite3_step(stmt) == SQLITE_ROW {
		if let text = sqlite3_column_text(stmt, 0) {
			return String(cString: text)
		}
	}
	return nil
}

func saveCachedTranscript(noteId: Int64, noteUUID: String, mediaUUID: String, title: String, dateStr: String, duration: Double, transcript: String) {
	guard let db = getTranscriptDB() else { return }
	defer { sqlite3_close(db) }

	let sql = """
	INSERT OR REPLACE INTO transcripts (note_id, note_uuid, media_uuid, title, date_str, duration, transcript, created_at)
	VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'));
	"""
	var stmt: OpaquePointer?
	guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
	defer { sqlite3_finalize(stmt) }

	sqlite3_bind_int64(stmt, 1, noteId)
	sqlite3_bind_text(stmt, 2, (noteUUID as NSString).utf8String, -1, nil)
	sqlite3_bind_text(stmt, 3, (mediaUUID as NSString).utf8String, -1, nil)
	sqlite3_bind_text(stmt, 4, (title as NSString).utf8String, -1, nil)
	sqlite3_bind_text(stmt, 5, (dateStr as NSString).utf8String, -1, nil)
	sqlite3_bind_double(stmt, 6, duration)
	sqlite3_bind_text(stmt, 7, (transcript as NSString).utf8String, -1, nil)

	sqlite3_step(stmt)
}

// MARK: - Audio Discovery

func resolveAudioPath(mediaUUID: String?, filename: String?) -> String? {
	guard let mediaUUID = mediaUUID, !mediaUUID.isEmpty else { return nil }
	let accountsDir = (notesBaseDir as NSString).appendingPathComponent("Accounts")
	guard let accounts = try? FileManager.default.contentsOfDirectory(atPath: accountsDir) else { return nil }

	for acc in accounts {
		let mediaDir = ((accountsDir as NSString).appendingPathComponent(acc) as NSString)
			.appendingPathComponent("Media/\(mediaUUID)")
		if FileManager.default.fileExists(atPath: mediaDir) {
			let enumerator = FileManager.default.enumerator(atPath: mediaDir)
			while let sub = enumerator?.nextObject() as? String {
				if sub.hasSuffix(".m4a") {
					return (mediaDir as NSString).appendingPathComponent(sub)
				}
			}
		}
	}
	return nil
}

func getAudioDuration(filePath: String) -> Double? {
	guard FileManager.default.fileExists(atPath: filePath) else { return nil }
	let url = URL(fileURLWithPath: filePath)
	let asset = AVURLAsset(url: url)
	let duration = CMTimeGetSeconds(asset.duration)
	if duration.isFinite && duration > 0 {
		return duration
	}
	return nil
}

func formatDuration(_ seconds: Double?) -> String {
	guard let sec = seconds, sec > 0 else { return "--:--" }
	let totalSec = Int(sec.rounded())
	let m = totalSec / 60
	let s = totalSec % 60
	return String(format: "%02d:%02d", m, s)
}

func formatFileSize(filePath: String?) -> String {
	guard let path = filePath, let attrs = try? FileManager.default.attributesOfItem(atPath: path),
		  let size = attrs[.size] as? Int64 else {
		return "missing"
	}
	let mb = Double(size) / (1024 * 1024)
	if mb >= 1.0 {
		return String(format: "%.1f MB", mb)
	}
	let kb = Double(size) / 1024
	return String(format: "%.0f KB", kb)
}

func formatDate(_ date: Date) -> String {
	let df = DateFormatter()
	df.dateFormat = "yyyy-MM-dd HH:mm"
	return df.string(from: date)
}

// MARK: - Query Notes

func fetchCallRecords() -> [CallRecord] {
	guard let db = getNotesDB() else { return [] }
	defer { sqlite3_close(db) }

	let query = """
	SELECT 
		n.Z_PK,
		COALESCE(n.ZIDENTIFIER, ''),
		COALESCE(n.ZTITLE1, 'Call Recording'),
		COALESCE(n.ZCREATIONDATE3, n.ZCREATIONDATE, 0.0),
		COALESCE(n.ZMODIFICATIONDATE1, 0.0),
		med.ZIDENTIFIER,
		med.ZFILENAME
	FROM ZICCLOUDSYNCINGOBJECT n
	LEFT JOIN ZICCLOUDSYNCINGOBJECT att ON att.ZNOTE = n.Z_PK AND (att.ZTYPEUTI = 'com.apple.m4a-audio' OR att.ZTYPEUTI LIKE '%audio%')
	LEFT JOIN ZICCLOUDSYNCINGOBJECT med ON med.Z_PK = att.ZMEDIA
	WHERE (n.ZHOSTAPPLICATIONIDENTIFIER = 'com.apple.mobilephone' OR n.ZTITLE1 LIKE 'Call Recording%')
	  AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION = 0)
	ORDER BY n.ZCREATIONDATE3 DESC, (CASE WHEN med.ZFILENAME LIKE '%.m4a' THEN 1 ELSE 2 END) ASC;
	"""

	var stmt: OpaquePointer?
	guard sqlite3_prepare_v2(db, query, -1, &stmt, nil) == SQLITE_OK else {
		let errMsg = String(cString: sqlite3_errmsg(db))
		fputs("Error executing query: \(errMsg)\n", stderr)
		return []
	}
	defer { sqlite3_finalize(stmt) }

	var records: [CallRecord] = []
	var seenIds = Set<Int64>()

	while sqlite3_step(stmt) == SQLITE_ROW {
		let pk = sqlite3_column_int64(stmt, 0)
		if seenIds.contains(pk) { continue }
		seenIds.insert(pk)

		let uuid = columnText(stmt, 1)
		var title = columnText(stmt, 2)
		if title.isEmpty {
			title = "Call Recording"
		}
		let rawCreated = sqlite3_column_double(stmt, 3)
		let rawModified = sqlite3_column_double(stmt, 4)

		let createdDate = Date(timeIntervalSinceReferenceDate: rawCreated)
		let modifiedDate = Date(timeIntervalSinceReferenceDate: rawModified)

		let mediaUUID = columnTextOpt(stmt, 5)
		let mediaFilename = columnTextOpt(stmt, 6)

		let audioPath = resolveAudioPath(mediaUUID: mediaUUID, filename: mediaFilename)
		let duration = audioPath != nil ? getAudioDuration(filePath: audioPath!) : nil
		let transcript = getCachedTranscript(noteId: pk)

		records.append(CallRecord(
			noteId: pk,
			noteUUID: uuid,
			title: title,
			createdAt: createdDate,
			modifiedAt: modifiedDate,
			mediaUUID: mediaUUID,
			mediaFilename: mediaFilename,
			localAudioPath: audioPath,
			durationSeconds: duration,
			transcript: transcript
		))
	}

	return records
}

// MARK: - Speech Recognition

func resolveSpeechRecognizer(localeIdentifier: String?) -> SFSpeechRecognizer? {
	let raw = localeIdentifier?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
	if raw.isEmpty {
		if let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), rec.isAvailable {
			return rec
		}
		return SFSpeechRecognizer()
	}
	let lower = raw.lowercased()
	var candidates: [String] = []
	switch lower {
	case "es", "spanish", "es-419":
		candidates = ["es-419", "es-ES", "es-US", "es-MX", "es"]
	case "en", "english", "en-us":
		candidates = ["en-US", "en-GB", "en-CA", "en-AU", "en"]
	case "fr", "french":
		candidates = ["fr-FR", "fr-CA", "fr"]
	case "de", "german":
		candidates = ["de-DE", "de-AT", "de-CH", "de"]
	case "it", "italian":
		candidates = ["it-IT", "it"]
	case "pt", "portuguese":
		candidates = ["pt-BR", "pt-PT", "pt"]
	case "ru", "russian":
		candidates = ["ru-RU", "ru"]
	case "zh", "chinese":
		candidates = ["zh-CN", "zh-TW", "zh-HK"]
	case "ja", "japanese":
		candidates = ["ja-JP", "ja"]
	case "ko", "korean":
		candidates = ["ko-KR", "ko"]
	case "ar", "arabic":
		candidates = ["ar-SA", "ar"]
	default:
		candidates = [raw, raw.replacingOccurrences(of: "_", with: "-")]
	}
	for id in candidates {
		if let rec = SFSpeechRecognizer(locale: Locale(identifier: id)), rec.isAvailable {
			return rec
		}
	}
	if let rec = SFSpeechRecognizer(locale: Locale(identifier: raw)), rec.isAvailable {
		return rec
	}
	fputs("Warning: Speech recognizer not available for '\(raw)'. Falling back to default.\n", stderr)
	return SFSpeechRecognizer()
}

func transcribeAudio(filePath: String, duration: Double?, lang: String?) -> String? {
	guard FileManager.default.fileExists(atPath: filePath) else { return nil }
	let fileURL = URL(fileURLWithPath: filePath)
	guard let recognizer = resolveSpeechRecognizer(localeIdentifier: lang), recognizer.isAvailable else {
		fputs("Error: Speech recognizer is not available on this system.\n", stderr)
		return nil
	}

	let request = SFSpeechURLRecognitionRequest(url: fileURL)
	if recognizer.supportsOnDeviceRecognition {
		request.requiresOnDeviceRecognition = true
	}

	var words: [String] = []
	var maxTimestamp: TimeInterval = -1.0
	var isDone = false

	let task = recognizer.recognitionTask(with: request) { result, error in
		if let result = result {
			for seg in result.bestTranscription.segments {
				if seg.timestamp > maxTimestamp {
					maxTimestamp = seg.timestamp
					words.append(seg.substring)
				}
			}
			if result.isFinal {
				isDone = true
			}
		}
		if error != nil {
			isDone = true
		}
	}

	let dur = duration ?? 60.0
	let timeout = max(30.0, dur * 2.0 + 10.0)
	let deadline = Date().addingTimeInterval(timeout)
	var lastReport = Date()

	while !isDone && Date() < deadline {
		RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.2))
		if Date().timeIntervalSince(lastReport) >= 5.0 {
			lastReport = Date()
			fputs("[\(words.count) words]... ", stderr)
		}
	}

	if !isDone {
		task.cancel()
	}

	return words.isEmpty ? nil : words.joined(separator: " ")
}

// MARK: - Actions

func pad(_ s: String, _ len: Int) -> String {
	if s.count >= len { return String(s.prefix(len)) }
	return s.padding(toLength: len, withPad: " ", startingAt: 0)
}

func listCalls(limit: Int?, includeAll: Bool, jsonOutput: Bool) {
	let records = fetchCallRecords()
	let count = includeAll ? records.count : (limit ?? 10)
	let slice = Array(records.prefix(count))

	if jsonOutput {
		var arr: [[String: Any]] = []
		for r in slice {
			var d: [String: Any] = [
				"id": r.noteId,
				"uuid": r.noteUUID,
				"title": r.title,
				"created": formatDate(r.createdAt),
				"duration_seconds": r.durationSeconds ?? 0,
				"duration_formatted": formatDuration(r.durationSeconds),
				"has_audio": r.localAudioPath != nil,
				"audio_size": formatFileSize(filePath: r.localAudioPath),
				"is_transcribed": r.transcript != nil
			]
			if let t = r.transcript { d["transcript"] = t }
			if let p = r.localAudioPath { d["audio_path"] = p }
			arr.append(d)
		}
		if let data = try? JSONSerialization.data(withJSONObject: arr, options: [.prettyPrinted]),
		   let jsonStr = String(data: data, encoding: .utf8) {
			print(jsonStr)
		}
		return
	}

	if slice.isEmpty {
		print("No call recordings found in Apple Notes.")
		return
	}

	print("\(pad("ID", 5)) | \(pad("DATE", 16)) | \(pad("DUR", 7)) | \(pad("AUDIO", 8)) | \(pad("TITLE", 32)) | TRANSCRIPT PREVIEW")
	print(String(repeating: "-", count: 100))

	for r in slice {
		let preview: String
		if let t = r.transcript, !t.isEmpty {
			preview = t.replacingOccurrences(of: "\n", with: " ")
		} else {
			preview = "(not transcribed)"
		}
		let trimmedPreview = preview.count > 35 ? String(preview.prefix(32)) + "..." : preview
		let trimmedTitle = r.title.count > 30 ? String(r.title.prefix(27)) + "..." : r.title

		print("\(pad(String(r.noteId), 5)) | \(pad(formatDate(r.createdAt), 16)) | \(pad(formatDuration(r.durationSeconds), 7)) | \(pad(formatFileSize(filePath: r.localAudioPath), 8)) | \(pad(trimmedTitle, 32)) | \(trimmedPreview)")
	}
}

func readCall(target: String, jsonOutput: Bool) {
	let records = fetchCallRecords()
	guard let r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	if jsonOutput {
		let d: [String: Any] = [
			"id": r.noteId,
			"uuid": r.noteUUID,
			"title": r.title,
			"created": formatDate(r.createdAt),
			"modified": formatDate(r.modifiedAt),
			"duration_seconds": r.durationSeconds ?? 0,
			"duration_formatted": formatDuration(r.durationSeconds),
			"has_audio": r.localAudioPath != nil,
			"audio_path": r.localAudioPath ?? "",
			"audio_size": formatFileSize(filePath: r.localAudioPath),
			"is_transcribed": r.transcript != nil,
			"transcript": r.transcript ?? ""
		]
		if let data = try? JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted]),
		   let jsonStr = String(data: data, encoding: .utf8) {
			print(jsonStr)
		}
		return
	}

	print("# Call Recording [\(r.noteId)]")
	print("Title:      \(r.title)")
	print("Date:       \(formatDate(r.createdAt))")
	print("Duration:   \(formatDuration(r.durationSeconds))")
	print("Audio File: \(r.localAudioPath ?? "Not found on disk")")
	print("Audio Size: \(formatFileSize(filePath: r.localAudioPath))")
	print("")

	if let t = r.transcript, !t.isEmpty {
		print("## Transcript")
		print(t)
	} else {
		print("## Transcript")
		print("(Not transcribed yet. Run `call-recordings transcribe \(r.noteId)` to transcribe locally)")
	}
}

func transcribeCall(target: String, lang: String?, force: Bool) {
	let records = fetchCallRecords()

	let toProcess: [CallRecord]
	if target == "--all" {
		toProcess = records
	} else {
		guard let match = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
			fputs("Error: Call recording '\(target)' not found.\n", stderr)
			exit(1)
		}
		toProcess = [match]
	}

	for r in toProcess {
		if !force, let cached = r.transcript, !cached.isEmpty {
			print("[\(r.noteId)] \"\(r.title)\" (Already cached):")
			print(cached)
			print("")
			continue
		}

		guard let audioPath = r.localAudioPath else {
			print("[\(r.noteId)] \"\(r.title)\": No local audio file found on disk.")
			continue
		}

		print("[\(r.noteId)] \"\(r.title)\" (\(formatDuration(r.durationSeconds))) transcribing...", terminator: " ")
		fflush(stdout)

		if let text = transcribeAudio(filePath: audioPath, duration: r.durationSeconds, lang: lang), !text.isEmpty {
			saveCachedTranscript(
				noteId: r.noteId,
				noteUUID: r.noteUUID,
				mediaUUID: r.mediaUUID ?? "",
				title: r.title,
				dateStr: formatDate(r.createdAt),
				duration: r.durationSeconds ?? 0,
				transcript: text
			)
			print("done.")
			print("--------------------------------------------------------------------------------")
			print(text)
			print("--------------------------------------------------------------------------------\n")
		} else {
			print("failed or returned empty transcript.")
		}
	}
}

func searchCalls(query: String) {
	let cleanQuery = query.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
	guard !cleanQuery.isEmpty else {
		fputs("Error: Search query cannot be empty.\n", stderr)
		exit(1)
	}

	let records = fetchCallRecords()
	var matches: [(record: CallRecord, matchType: String, snippet: String)] = []
	var untranscribedCount = 0

	for r in records {
		if r.transcript == nil || r.transcript!.isEmpty {
			untranscribedCount += 1
		}
		if r.title.lowercased().contains(cleanQuery) {
			matches.append((r, "Title", r.title))
			continue
		}
		if let t = r.transcript, t.lowercased().contains(cleanQuery) {
			let lower = t.lowercased()
			if let range = lower.range(of: cleanQuery) {
				let start = t.index(range.lowerBound, offsetBy: -30, limitedBy: t.startIndex) ?? t.startIndex
				let end = t.index(range.upperBound, offsetBy: 60, limitedBy: t.endIndex) ?? t.endIndex
				let snippet = "..." + t[start..<end].replacingOccurrences(of: "\n", with: " ") + "..."
				matches.append((r, "Transcript", snippet))
			}
		}
	}

	if matches.isEmpty {
		print("No call recordings found matching '\(query)'.")
		if untranscribedCount > 0 {
			print("Notice: \(untranscribedCount) recording(s) have not been transcribed yet. Run `call-recordings transcribe --all` to index all audio.")
		}
		return
	}

	print("Found \(matches.count) recording(s) matching '\(query)':\n")
	for m in matches {
		let r = m.record
		print("[\(r.noteId)] \(formatDate(r.createdAt)) | \(r.title) (\(formatDuration(r.durationSeconds)))")
		print("      Matched \(m.matchType): \(m.snippet)\n")
	}

	if untranscribedCount > 0 {
		print("Note: \(untranscribedCount) other recording(s) are not yet transcribed. Run `call-recordings transcribe --all` to search all recordings.")
	}
}

func exportCall(target: String, outDestination: String?) {
	let records = fetchCallRecords()
	guard let r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	guard let src = r.localAudioPath, FileManager.default.fileExists(atPath: src) else {
		fputs("Error: Audio file not found on disk for note [\(r.noteId)].\n", stderr)
		exit(1)
	}

	let df = DateFormatter()
	df.dateFormat = "yyyy-MM-dd_HHmm"
	let safeTitle = r.title.replacingOccurrences(of: " ", with: "_").components(separatedBy: CharacterSet.alphanumerics.inverted.subtracting(CharacterSet(charactersIn: "_-"))).joined()
	let defaultName = "\(df.string(from: r.createdAt))_\(safeTitle).m4a"

	let destPath: String
	if let out = outDestination {
		let expanded = (out as NSString).expandingTildeInPath
		var isDir: ObjCBool = false
		if FileManager.default.fileExists(atPath: expanded, isDirectory: &isDir) && isDir.boolValue {
			destPath = (expanded as NSString).appendingPathComponent(defaultName)
		} else {
			destPath = expanded
		}
	} else {
		destPath = (FileManager.default.currentDirectoryPath as NSString).appendingPathComponent(defaultName)
	}

	do {
		if FileManager.default.fileExists(atPath: destPath) {
			try FileManager.default.removeItem(atPath: destPath)
		}
		try FileManager.default.copyItem(atPath: src, toPath: destPath)
		print("Exported audio to: \(destPath)")
	} catch {
		fputs("Error copying file to \(destPath): \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

func openCall(target: String) {
	let records = fetchCallRecords()
	guard let r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	let script = """
	tell application "Notes"
		activate
		try
			set targetNote to first note whose id ends with "/p\(r.noteId)"
			show targetNote
		on error
			display alert "Could not open note [\(r.noteId)]"
		end try
	end tell
	"""

	var error: NSDictionary?
	if let appleScript = NSAppleScript(source: script) {
		appleScript.executeAndReturnError(&error)
		if let err = error {
			fputs("AppleScript error: \(err)\n", stderr)
		} else {
			print("Opened call recording note [\(r.noteId)] in Apple Notes.")
		}
	}
}

// MARK: - Usage & Main

func printUsage() {
	let usage = """
	call-recordings - CLI to access, transcribe, and export iPhone call recordings from Apple Notes

	Usage:
	  call-recordings [list] [--limit <N>] [--all] [--json]
	  call-recordings read <id|title> [--json]
	  call-recordings transcribe <id|--all> [--lang <code>] [--force]
	  call-recordings search "<query>"
	  call-recordings export <id> [--out <dir|file>]
	  call-recordings open <id>

	Commands:
	  list          List all iPhone call recordings with date, duration, size, and transcripts (default)
	  read          View full metadata, audio path, and transcript of a call
	  transcribe    Transcribe call recording audio locally via macOS Speech framework
	  search        Full-text search through call titles and transcribed conversations
	  export        Copy the recording .m4a audio file to a folder or file path
	  open          Reveal and open the recording note in the macOS Notes application

	Options:
	  --limit <N>   Number of calls to list (default: 10)
	  --all         Include all call recordings (no limit)
	  --json        Output in structured JSON format
	  --lang <code> Language code or name for speech recognition (e.g. en-US, es, fr; default: en-US)
	  --force       Force re-transcription even if already cached
	  --out <path>  Output folder or filepath for export (default: current directory)
	  --help, -h    Show this help message

	Examples:
	  call-recordings
	  call-recordings list --all
	  call-recordings read 592
	  call-recordings transcribe 592
	  call-recordings transcribe --all
	  call-recordings search "RBC"
	  call-recordings export 592 --out ~/Downloads
	  call-recordings open 592
	"""
	print(usage)
}

func main() {
	let args = CommandLine.arguments

	if args.count <= 1 || args.contains("--help") || args.contains("-h") {
		if args.count <= 1 {
			listCalls(limit: 10, includeAll: false, jsonOutput: false)
			return
		}
		printUsage()
		return
	}

	let sub = args[1]
	switch sub {
	case "list":
		var limit: Int? = nil
		var includeAll = false
		var jsonOutput = false
		var i = 2
		while i < args.count {
			if args[i] == "--limit" && i + 1 < args.count {
				limit = Int(args[i + 1])
				i += 1
			} else if args[i] == "--all" {
				includeAll = true
			} else if args[i] == "--json" {
				jsonOutput = true
			}
			i += 1
		}
		listCalls(limit: limit, includeAll: includeAll, jsonOutput: jsonOutput)

	case "read":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings read <id|title> [--json]\n", stderr)
			exit(1)
		}
		let target = args[2]
		let jsonOutput = args.contains("--json")
		readCall(target: target, jsonOutput: jsonOutput)

	case "transcribe":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings transcribe <id|--all> [--lang <code>] [--force]\n", stderr)
			exit(1)
		}
		let target = args[2]
		var lang: String? = nil
		var force = false
		var i = 3
		while i < args.count {
			if (args[i] == "--lang" || args[i] == "-l") && i + 1 < args.count {
				lang = args[i + 1]
				i += 1
			} else if args[i] == "--force" {
				force = true
			}
			i += 1
		}
		transcribeCall(target: target, lang: lang, force: force)

	case "search":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings search \"<query>\"\n", stderr)
			exit(1)
		}
		let query = args[2]
		searchCalls(query: query)

	case "export":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings export <id> [--out <dir|file>]\n", stderr)
			exit(1)
		}
		let target = args[2]
		var outDest: String? = nil
		var i = 3
		while i < args.count {
			if (args[i] == "--out" || args[i] == "-o") && i + 1 < args.count {
				outDest = args[i + 1]
				i += 1
			}
			i += 1
		}
		exportCall(target: target, outDestination: outDest)

	case "open":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings open <id>\n", stderr)
			exit(1)
		}
		let target = args[2]
		openCall(target: target)

	default:
		// If first argument is a numeric ID, treat as read
		if Int(sub) != nil {
			readCall(target: sub, jsonOutput: args.contains("--json"))
		} else {
			fputs("Unknown command: '\(sub)'. Run 'call-recordings --help' for usage.\n", stderr)
			exit(1)
		}
	}
}

main()
