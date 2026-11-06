#!/usr/bin/env swift

import Foundation
import SQLite3
import Speech
import AVFoundation

// ============================================================================
// call-recordings: CLI to list, inspect, transcribe, search, clip, and backup
// iPhone call recordings from Apple Notes.
// Features: FTS5 Porter search, Dual-Track Speaker Diarization, Audio Clipping
// ============================================================================

struct TranscriptSegment {
	let startTime: Double
	let endTime: Double
	let speaker: String
	let text: String
}

struct CallRecord {
	let noteId: Int64
	let noteUUID: String
	let title: String
	let createdAt: Date
	let modifiedAt: Date
	let mediaUUID: String?
	let movUUID: String?
	var localAudioPath: String?
	var localMovPath: String?
	var durationSeconds: Double?
	var transcript: String?
}

enum DateFilter {
	case none
	case today
	case yesterday
	case sinceDays(Int)
}

// MARK: - Paths & Helpers

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

func formatTime(_ sec: Double) -> String {
	let total = max(0, Int(sec.rounded()))
	let m = total / 60
	let s = total % 60
	return String(format: "%02d:%02d", m, s)
}

func parseTime(_ str: String) -> Double? {
	if let sec = Double(str) { return sec }
	let parts = str.split(separator: ":").map { Double($0) ?? 0 }
	if parts.count == 2 {
		return parts[0] * 60 + parts[1]
	} else if parts.count == 3 {
		return parts[0] * 3600 + parts[1] * 60 + parts[2]
	}
	return nil
}

func resolveGoogleDriveDir() -> String? {
	if let env = ProcessInfo.processInfo.environment["CALL_RECORDINGS_BACKUP_DIR"], !env.isEmpty {
		let expanded = (env as NSString).expandingTildeInPath
		if FileManager.default.fileExists(atPath: expanded) {
			return expanded
		}
	}
	let cloudStorage = ("~/Library/CloudStorage" as NSString).expandingTildeInPath
	if let items = try? FileManager.default.contentsOfDirectory(atPath: cloudStorage) {
		for item in items where item.hasPrefix("GoogleDrive-") && !item.contains("(") {
			let myDrive = ((cloudStorage as NSString).appendingPathComponent(item) as NSString).appendingPathComponent("My Drive")
			if FileManager.default.fileExists(atPath: myDrive) {
				return myDrive
			}
		}
		for item in items where item.hasPrefix("GoogleDrive-") {
			let myDrive = ((cloudStorage as NSString).appendingPathComponent(item) as NSString).appendingPathComponent("My Drive")
			if FileManager.default.fileExists(atPath: myDrive) {
				return myDrive
			}
		}
	}
	let classic = ("~/Google Drive/My Drive" as NSString).expandingTildeInPath
	if FileManager.default.fileExists(atPath: classic) { return classic }
	let classic2 = ("~/Google Drive" as NSString).expandingTildeInPath
	if FileManager.default.fileExists(atPath: classic2) { return classic2 }
	return nil
}

// MARK: - Database Setup

func ensureLocalDatabase() {
	if !FileManager.default.fileExists(atPath: transcriptDBPath) {
		if let gdrive = resolveGoogleDriveDir() {
			let remoteDB = ((gdrive as NSString).appendingPathComponent("call-recordings") as NSString).appendingPathComponent("transcripts.sqlite")
			if FileManager.default.fileExists(atPath: remoteDB) {
				try? FileManager.default.createDirectory(atPath: cacheDir, withIntermediateDirectories: true, attributes: nil)
				if (try? FileManager.default.copyItem(atPath: remoteDB, toPath: transcriptDBPath)) != nil {
					print("Restored call database snapshot from Google Drive.")
				}
			}
		}
	}
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
	CREATE TABLE IF NOT EXISTS transcript_segments (
		note_id INTEGER,
		start_time REAL,
		end_time REAL,
		speaker TEXT,
		text TEXT
	);
	CREATE INDEX IF NOT EXISTS idx_transcripts_title ON transcripts(title);
	CREATE INDEX IF NOT EXISTS idx_transcripts_uuid ON transcripts(note_uuid);
	CREATE INDEX IF NOT EXISTS idx_segments_note ON transcript_segments(note_id);
	CREATE INDEX IF NOT EXISTS idx_segments_time ON transcript_segments(start_time);

	CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
		note_id UNINDEXED,
		title,
		transcript,
		tokenize='porter unicode61'
	);
	CREATE VIRTUAL TABLE IF NOT EXISTS transcript_segments_fts USING fts5(
		note_id UNINDEXED,
		start_time UNINDEXED,
		end_time UNINDEXED,
		speaker UNINDEXED,
		text,
		tokenize='porter unicode61'
	);
	"""
	sqlite3_exec(db, createSQL, nil, nil, nil)

	// One-time backfill of FTS5 if newly created
	let backfillSQL = """
	INSERT INTO transcripts_fts (note_id, title, transcript)
	SELECT note_id, title, transcript FROM transcripts
	WHERE note_id NOT IN (SELECT note_id FROM transcripts_fts);

	INSERT INTO transcript_segments_fts (note_id, start_time, end_time, speaker, text)
	SELECT note_id, start_time, end_time, speaker, text FROM transcript_segments
	WHERE note_id NOT IN (SELECT note_id FROM transcript_segments_fts);
	"""
	sqlite3_exec(db, backfillSQL, nil, nil, nil)

	return db
}

func sanitizeFtsQuery(_ raw: String) -> String {
	let tokens = raw.components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }
	if tokens.isEmpty { return "\"\(raw.replacingOccurrences(of: "\"", with: ""))\"" }
	return tokens.map { "\"\($0)\"" }.joined(separator: " ")
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

func getCachedSegments(noteId: Int64) -> [TranscriptSegment] {
	guard let db = getTranscriptDB() else { return [] }
	defer { sqlite3_close(db) }

	let query = "SELECT start_time, end_time, speaker, text FROM transcript_segments WHERE note_id = ? ORDER BY start_time ASC;"
	var stmt: OpaquePointer?
	guard sqlite3_prepare_v2(db, query, -1, &stmt, nil) == SQLITE_OK else { return [] }
	defer { sqlite3_finalize(stmt) }

	sqlite3_bind_int64(stmt, 1, noteId)
	var segs: [TranscriptSegment] = []
	while sqlite3_step(stmt) == SQLITE_ROW {
		let start = sqlite3_column_double(stmt, 0)
		let end = sqlite3_column_double(stmt, 1)
		let spk = columnText(stmt, 2)
		let txt = columnText(stmt, 3)
		segs.append(TranscriptSegment(startTime: start, endTime: end, speaker: spk, text: txt))
	}
	return segs
}

func saveCachedTranscript(noteId: Int64, noteUUID: String, mediaUUID: String, title: String, dateStr: String, duration: Double, transcript: String, segments: [TranscriptSegment] = []) {
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

	// Update FTS5
	var delStmt: OpaquePointer?
	if sqlite3_prepare_v2(db, "DELETE FROM transcripts_fts WHERE note_id = ?;", -1, &delStmt, nil) == SQLITE_OK {
		sqlite3_bind_int64(delStmt, 1, noteId)
		sqlite3_step(delStmt)
		sqlite3_finalize(delStmt)
	}

	var ftsStmt: OpaquePointer?
	if sqlite3_prepare_v2(db, "INSERT INTO transcripts_fts (note_id, title, transcript) VALUES (?, ?, ?);", -1, &ftsStmt, nil) == SQLITE_OK {
		sqlite3_bind_int64(ftsStmt, 1, noteId)
		sqlite3_bind_text(ftsStmt, 2, (title as NSString).utf8String, -1, nil)
		sqlite3_bind_text(ftsStmt, 3, (transcript as NSString).utf8String, -1, nil)
		sqlite3_step(ftsStmt)
		sqlite3_finalize(ftsStmt)
	}

	// Update Segments
	if !segments.isEmpty {
		var delSegStmt: OpaquePointer?
		if sqlite3_prepare_v2(db, "DELETE FROM transcript_segments WHERE note_id = ?;", -1, &delSegStmt, nil) == SQLITE_OK {
			sqlite3_bind_int64(delSegStmt, 1, noteId)
			sqlite3_step(delSegStmt)
			sqlite3_finalize(delSegStmt)
		}

		let insSegSQL = "INSERT INTO transcript_segments (note_id, start_time, end_time, speaker, text) VALUES (?, ?, ?, ?, ?);"
		var insSegStmt: OpaquePointer?
		if sqlite3_prepare_v2(db, insSegSQL, -1, &insSegStmt, nil) == SQLITE_OK {
			for s in segments {
				sqlite3_bind_int64(insSegStmt, 1, noteId)
				sqlite3_bind_double(insSegStmt, 2, s.startTime)
				sqlite3_bind_double(insSegStmt, 3, s.endTime)
				sqlite3_bind_text(insSegStmt, 4, (s.speaker as NSString).utf8String, -1, nil)
				sqlite3_bind_text(insSegStmt, 5, (s.text as NSString).utf8String, -1, nil)
				sqlite3_step(insSegStmt)
				sqlite3_reset(insSegStmt)
			}
			sqlite3_finalize(insSegStmt)
		}

		// Update Segments FTS
		var delSegFtsStmt: OpaquePointer?
		if sqlite3_prepare_v2(db, "DELETE FROM transcript_segments_fts WHERE note_id = ?;", -1, &delSegFtsStmt, nil) == SQLITE_OK {
			sqlite3_bind_int64(delSegFtsStmt, 1, noteId)
			sqlite3_step(delSegFtsStmt)
			sqlite3_finalize(delSegFtsStmt)
		}

		let insSegFtsSQL = "INSERT INTO transcript_segments_fts (note_id, start_time, end_time, speaker, text) VALUES (?, ?, ?, ?, ?);"
		var insSegFtsStmt: OpaquePointer?
		if sqlite3_prepare_v2(db, insSegFtsSQL, -1, &insSegFtsStmt, nil) == SQLITE_OK {
			for s in segments {
				sqlite3_bind_int64(insSegFtsStmt, 1, noteId)
				sqlite3_bind_double(insSegFtsStmt, 2, s.startTime)
				sqlite3_bind_double(insSegFtsStmt, 3, s.endTime)
				sqlite3_bind_text(insSegFtsStmt, 4, (s.speaker as NSString).utf8String, -1, nil)
				sqlite3_bind_text(insSegFtsStmt, 5, (s.text as NSString).utf8String, -1, nil)
				sqlite3_step(insSegFtsStmt)
				sqlite3_reset(insSegFtsStmt)
			}
			sqlite3_finalize(insSegFtsStmt)
		}
	}
}

func backupDatabase(sourceDB: OpaquePointer?, destPath: String) -> Bool {
	var destDB: OpaquePointer?
	if sqlite3_open(destPath, &destDB) != SQLITE_OK {
		return false
	}
	defer { sqlite3_close(destDB) }

	guard let backup = sqlite3_backup_init(destDB, "main", sourceDB, "main") else {
		return false
	}
	let stepRes = sqlite3_backup_step(backup, -1)
	sqlite3_backup_finish(backup)
	return stepRes == SQLITE_DONE
}

// MARK: - Audio Discovery & Energy Diarization

func resolveMediaFile(mediaUUID: String?, extensionName: String) -> String? {
	guard let mediaUUID = mediaUUID, !mediaUUID.isEmpty else { return nil }
	let accountsDir = (notesBaseDir as NSString).appendingPathComponent("Accounts")
	guard let accounts = try? FileManager.default.contentsOfDirectory(atPath: accountsDir) else { return nil }

	for acc in accounts {
		let mediaDir = ((accountsDir as NSString).appendingPathComponent(acc) as NSString)
			.appendingPathComponent("Media/\(mediaUUID)")
		if FileManager.default.fileExists(atPath: mediaDir) {
			let enumerator = FileManager.default.enumerator(atPath: mediaDir)
			while let sub = enumerator?.nextObject() as? String {
				if sub.hasSuffix(extensionName) {
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
	return formatTime(sec)
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

// Check energy on Track 0 (You/mic) vs Track 1 (Remote/telephony)
func detectSpeakerAtTime(movPath: String, time: Double) -> String {
	let url = URL(fileURLWithPath: movPath)
	let asset = AVURLAsset(url: url)
	let tracks = asset.tracks(withMediaType: .audio)
	guard tracks.count >= 2 else { return "" }

	func sampleEnergy(track: AVAssetTrack, at t: Double) -> Float {
		guard let reader = try? AVAssetReader(asset: asset) else { return 0 }
		let startCM = CMTime(seconds: max(0, t - 0.2), preferredTimescale: 44100)
		let durCM = CMTime(seconds: 0.4, preferredTimescale: 44100)
		reader.timeRange = CMTimeRange(start: startCM, duration: durCM)
		let settings: [String: Any] = [
			AVFormatIDKey: kAudioFormatLinearPCM,
			AVLinearPCMBitDepthKey: 16,
			AVLinearPCMIsFloatKey: false,
			AVLinearPCMIsBigEndianKey: false,
			AVNumberOfChannelsKey: 1
		]
		let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
		reader.add(output)
		reader.startReading()
		var sum: Float = 0
		var count = 0
		while let s = output.copyNextSampleBuffer() {
			if let b = CMSampleBufferGetDataBuffer(s) {
				let len = CMBlockBufferGetDataLength(b)
				var data = [Int16](repeating: 0, count: len / 2)
				CMBlockBufferCopyDataBytes(b, atOffset: 0, dataLength: len, destination: &data)
				for v in data { sum += abs(Float(v)); count += 1 }
			}
		}
		return count > 0 ? sum / Float(count) : 0
	}

	let e0 = sampleEnergy(track: tracks[0], at: time) // You
	let e1 = sampleEnergy(track: tracks[1], at: time) // Remote
	if e0 > e1 * 1.4 { return "You" }
	if e1 > e0 * 1.4 { return "Remote" }
	return ""
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
		(SELECT m.ZIDENTIFIER FROM ZICCLOUDSYNCINGOBJECT a JOIN ZICCLOUDSYNCINGOBJECT m ON m.Z_PK = a.ZMEDIA WHERE a.ZNOTE = n.Z_PK AND (m.ZFILENAME LIKE '%.m4a' OR m.ZFILENAME LIKE '%Recording%') LIMIT 1),
		(SELECT m.ZIDENTIFIER FROM ZICCLOUDSYNCINGOBJECT a JOIN ZICCLOUDSYNCINGOBJECT m ON m.Z_PK = a.ZMEDIA WHERE a.ZNOTE = n.Z_PK AND m.ZFILENAME LIKE '%.MOV' LIMIT 1)
	FROM ZICCLOUDSYNCINGOBJECT n
	WHERE (n.ZHOSTAPPLICATIONIDENTIFIER = 'com.apple.mobilephone' OR n.ZTITLE1 LIKE 'Call Recording%')
	  AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION = 0)
	ORDER BY n.ZCREATIONDATE3 DESC;
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
		let movUUID = columnTextOpt(stmt, 6)

		let audioPath = resolveMediaFile(mediaUUID: mediaUUID, extensionName: ".m4a")
		let movPath = resolveMediaFile(mediaUUID: movUUID, extensionName: ".MOV")
		let duration = audioPath != nil ? getAudioDuration(filePath: audioPath!) : nil
		let transcript = getCachedTranscript(noteId: pk)

		records.append(CallRecord(
			noteId: pk,
			noteUUID: uuid,
			title: title,
			createdAt: createdDate,
			modifiedAt: modifiedDate,
			mediaUUID: mediaUUID,
			movUUID: movUUID,
			localAudioPath: audioPath,
			localMovPath: movPath,
			durationSeconds: duration,
			transcript: transcript
		))
	}

	return records
}

// MARK: - Speech Recognition & Segment Generation

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

func transcribeAudio(filePath: String, movPath: String?, duration: Double?, lang: String?) -> (transcript: String, segments: [TranscriptSegment])? {
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

	var rawWords: [(word: String, start: Double, end: Double)] = []
	var maxTimestamp: TimeInterval = -1.0
	var isDone = false

	let task = recognizer.recognitionTask(with: request) { result, error in
		if let result = result {
			for seg in result.bestTranscription.segments {
				if seg.timestamp > maxTimestamp {
					maxTimestamp = seg.timestamp
					rawWords.append((word: seg.substring, start: seg.timestamp, end: seg.timestamp + seg.duration))
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
			fputs("[\(rawWords.count) words]... ", stderr)
		}
	}

	if !isDone {
		task.cancel()
	}

	guard !rawWords.isEmpty else { return nil }

	// Group raw words into natural dialogue sentences and assign speakers
	var segments: [TranscriptSegment] = []
	var currentSentence: [String] = []
	var segStart: Double = rawWords[0].start
	var segEnd: Double = rawWords[0].end

	for (i, w) in rawWords.enumerated() {
		currentSentence.append(w.word)
		segEnd = w.end

		let isLast = (i == rawWords.count - 1)
		let nextGap = !isLast ? (rawWords[i + 1].start - w.end) : 0
		let endsWithPunct = w.word.hasSuffix(".") || w.word.hasSuffix("?") || w.word.hasSuffix("!")

		if isLast || nextGap > 1.2 || (endsWithPunct && currentSentence.count >= 4) {
			let text = currentSentence.joined(separator: " ")
			var spk = ""
			if let mp = movPath, FileManager.default.fileExists(atPath: mp) {
				spk = detectSpeakerAtTime(movPath: mp, time: (segStart + segEnd) / 2.0)
			}
			segments.append(TranscriptSegment(startTime: segStart, endTime: segEnd, speaker: spk, text: text))

			currentSentence = []
			if !isLast {
				segStart = rawWords[i + 1].start
			}
		}
	}

	let fullText = rawWords.map { $0.word }.joined(separator: " ")
	return (transcript: fullText, segments: segments)
}

// MARK: - Actions

func pad(_ s: String, _ len: Int) -> String {
	if s.count >= len { return String(s.prefix(len)) }
	return s.padding(toLength: len, withPad: " ", startingAt: 0)
}

func listCalls(limit: Int?, includeAll: Bool, dateFilter: DateFilter, jsonOutput: Bool) {
	let records = fetchCallRecords()

	let filtered: [CallRecord]
	let calendar = Calendar.current
	switch dateFilter {
	case .today:
		filtered = records.filter { calendar.isDateInToday($0.createdAt) }
	case .yesterday:
		filtered = records.filter { calendar.isDateInYesterday($0.createdAt) }
	case .sinceDays(let days):
		if let cutoff = calendar.date(byAdding: .day, value: -days, to: Date()) {
			filtered = records.filter { $0.createdAt >= cutoff }
		} else {
			filtered = records
		}
	case .none:
		filtered = records
	}

	let count = includeAll ? filtered.count : (limit ?? 10)
	let slice = Array(filtered.prefix(count))

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
		print("No call recordings found.")
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

func readCall(target: String, autoTranscribe: Bool, jsonOutput: Bool) {
	let records = fetchCallRecords()
	guard var r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	if (r.transcript == nil || r.transcript!.isEmpty) && autoTranscribe {
		if let audioPath = r.localAudioPath {
			print("[\(r.noteId)] Transcribing audio on-the-fly...", terminator: " ")
			fflush(stdout)
			if let res = transcribeAudio(filePath: audioPath, movPath: r.localMovPath, duration: r.durationSeconds, lang: nil) {
				saveCachedTranscript(
					noteId: r.noteId,
					noteUUID: r.noteUUID,
					mediaUUID: r.mediaUUID ?? "",
					title: r.title,
					dateStr: formatDate(r.createdAt),
					duration: r.durationSeconds ?? 0,
					transcript: res.transcript,
					segments: res.segments
				)
				r.transcript = res.transcript
				print("done.\n")
			} else {
				print("failed.\n")
			}
		}
	}

	let segments = getCachedSegments(noteId: r.noteId)

	if jsonOutput {
		var segArray: [[String: Any]] = []
		for s in segments {
			segArray.append([
				"start": s.startTime,
				"end": s.endTime,
				"start_formatted": formatTime(s.startTime),
				"speaker": s.speaker,
				"text": s.text
			])
		}
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
			"transcript": r.transcript ?? "",
			"segments": segArray
		]
		if let data = try? JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted]),
		   let jsonStr = String(data: data, encoding: .utf8) {
			print(jsonStr)
		}
		return
	}

	print("# Call Recording [\(r.noteId)]")
	print("Title:      \(r.title)")
	print("UUID:       \(r.noteUUID)")
	print("Date:       \(formatDate(r.createdAt))")
	print("Duration:   \(formatDuration(r.durationSeconds))")
	print("Audio File: \(r.localAudioPath ?? "Not found on disk")")
	print("Audio Size: \(formatFileSize(filePath: r.localAudioPath))")
	print("")

	print("## Transcript")
	if !segments.isEmpty {
		for s in segments {
			let spkLabel = s.speaker.isEmpty ? "" : "(\(s.speaker)) "
			print("[\(formatTime(s.startTime))] \(spkLabel)\(s.text)")
		}
	} else if let t = r.transcript, !t.isEmpty {
		print(t)
	} else {
		print("(Not transcribed yet. Run `call-recordings read \(r.noteId) -t` or `transcribe \(r.noteId)`)")
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
			let segs = getCachedSegments(noteId: r.noteId)
			if !segs.isEmpty {
				for s in segs {
					let spk = s.speaker.isEmpty ? "" : "(\(s.speaker)) "
					print("[\(formatTime(s.startTime))] \(spk)\(s.text)")
				}
			} else {
				print(cached)
			}
			print("")
			continue
		}

		guard let audioPath = r.localAudioPath else {
			print("[\(r.noteId)] \"\(r.title)\": No local audio file found on disk.")
			continue
		}

		print("[\(r.noteId)] \"\(r.title)\" (\(formatDuration(r.durationSeconds))) transcribing...", terminator: " ")
		fflush(stdout)

		if let res = transcribeAudio(filePath: audioPath, movPath: r.localMovPath, duration: r.durationSeconds, lang: lang), !res.transcript.isEmpty {
			saveCachedTranscript(
				noteId: r.noteId,
				noteUUID: r.noteUUID,
				mediaUUID: r.mediaUUID ?? "",
				title: r.title,
				dateStr: formatDate(r.createdAt),
				duration: r.durationSeconds ?? 0,
				transcript: res.transcript,
				segments: res.segments
			)
			print("done.")
			print("--------------------------------------------------------------------------------")
			for s in res.segments {
				let spk = s.speaker.isEmpty ? "" : "(\(s.speaker)) "
				print("[\(formatTime(s.startTime))] \(spk)\(s.text)")
			}
			print("--------------------------------------------------------------------------------\n")
		} else {
			print("failed or returned empty transcript.")
		}
	}
}

func searchCalls(query: String, autoTranscribe: Bool) {
	let cleanQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
	guard !cleanQuery.isEmpty else {
		fputs("Error: Search query cannot be empty.\n", stderr)
		exit(1)
	}

	var records = fetchCallRecords()

	if autoTranscribe {
		for i in 0..<records.count {
			if records[i].transcript == nil || records[i].transcript!.isEmpty {
				if let p = records[i].localAudioPath {
					print("[\(records[i].noteId)] Transcribing \"\(records[i].title)\" for search...", terminator: " ")
					fflush(stdout)
					if let res = transcribeAudio(filePath: p, movPath: records[i].localMovPath, duration: records[i].durationSeconds, lang: nil) {
						saveCachedTranscript(
							noteId: records[i].noteId,
							noteUUID: records[i].noteUUID,
							mediaUUID: records[i].mediaUUID ?? "",
							title: records[i].title,
							dateStr: formatDate(records[i].createdAt),
							duration: records[i].durationSeconds ?? 0,
							transcript: res.transcript,
							segments: res.segments
						)
						records[i].transcript = res.transcript
						print("done.")
					} else {
						print("failed.")
					}
				}
			}
		}
	}

	guard let db = getTranscriptDB() else {
		fputs("Error: Could not open transcripts database.\n", stderr)
		return
	}
	defer { sqlite3_close(db) }

	// First query FTS5 with Porter Stemming
	var matchingNoteIds: [Int64] = []
	let sanitizedFts = sanitizeFtsQuery(cleanQuery)

	// 1. Query segments FTS first
	var segMatchesByNote: [Int64: [String]] = [:]
	let segFtsQuery = "SELECT note_id, start_time, speaker, text FROM transcript_segments_fts WHERE transcript_segments_fts MATCH ? ORDER BY note_id, start_time ASC;"
	var segFtsStmt: OpaquePointer?
	if sqlite3_prepare_v2(db, segFtsQuery, -1, &segFtsStmt, nil) == SQLITE_OK {
		sqlite3_bind_text(segFtsStmt, 1, (sanitizedFts as NSString).utf8String, -1, nil)
		while sqlite3_step(segFtsStmt) == SQLITE_ROW {
			let nid = sqlite3_column_int64(segFtsStmt, 0)
			let st = sqlite3_column_double(segFtsStmt, 1)
			let spk = columnText(segFtsStmt, 2)
			let txt = columnText(segFtsStmt, 3)
			let spkLabel = spk.isEmpty ? "" : "(\(spk)) "
			if segMatchesByNote[nid] == nil { segMatchesByNote[nid] = [] }
			segMatchesByNote[nid]?.append("At [\(formatTime(st))] \(spkLabel)\"\(txt)\"")
			if !matchingNoteIds.contains(nid) {
				matchingNoteIds.append(nid)
			}
		}
		sqlite3_finalize(segFtsStmt)
	}

	// 2. Also query full transcripts FTS for older recordings without segments
	let ftsQuery = "SELECT DISTINCT note_id FROM transcripts_fts WHERE transcripts_fts MATCH ?;"
	var stmt: OpaquePointer?
	if sqlite3_prepare_v2(db, ftsQuery, -1, &stmt, nil) == SQLITE_OK {
		sqlite3_bind_text(stmt, 1, (sanitizedFts as NSString).utf8String, -1, nil)
		while sqlite3_step(stmt) == SQLITE_ROW {
			let nid = sqlite3_column_int64(stmt, 0)
			if !matchingNoteIds.contains(nid) {
				matchingNoteIds.append(nid)
			}
		}
		sqlite3_finalize(stmt)
	}

	// Fallback to title and LIKE if FTS produced 0 results
	if matchingNoteIds.isEmpty {
		let likeQuery = "SELECT DISTINCT note_id FROM transcripts WHERE title LIKE ? OR transcript LIKE ?;"
		if sqlite3_prepare_v2(db, likeQuery, -1, &stmt, nil) == SQLITE_OK {
			let likeParam = "%\(cleanQuery)%"
			sqlite3_bind_text(stmt, 1, (likeParam as NSString).utf8String, -1, nil)
			sqlite3_bind_text(stmt, 2, (likeParam as NSString).utf8String, -1, nil)
			while sqlite3_step(stmt) == SQLITE_ROW {
				matchingNoteIds.append(sqlite3_column_int64(stmt, 0))
			}
			sqlite3_finalize(stmt)
		}
	}

	// Also check note titles in Notes DB directly
	for r in records {
		if r.title.lowercased().contains(cleanQuery.lowercased()) && !matchingNoteIds.contains(r.noteId) {
			matchingNoteIds.append(r.noteId)
		}
	}

	let untranscribedCount = records.filter { $0.transcript == nil || $0.transcript!.isEmpty }.count

	if matchingNoteIds.isEmpty {
		print("No call recordings found matching '\(query)'.")
		if untranscribedCount > 0 {
			print("Notice: \(untranscribedCount) recording(s) have not been transcribed yet. Run `call-recordings search \"\(query)\" -t` or `call-recordings sync`.")
		}
		return
	}

	print("Found \(matchingNoteIds.count) recording(s) matching '\(query)':\n")

	for id in matchingNoteIds {
		guard let r = records.first(where: { $0.noteId == id }) else { continue }
		var matchedSnippets: [String] = segMatchesByNote[id] ?? []

		if matchedSnippets.isEmpty {
			let segs = getCachedSegments(noteId: id)
			let qLower = cleanQuery.lowercased()
			for s in segs {
				if s.text.lowercased().contains(qLower) {
					let spk = s.speaker.isEmpty ? "" : "(\(s.speaker)) "
					matchedSnippets.append("At [\(formatTime(s.startTime))] \(spk)\"\(s.text)\"")
				}
			}
		}

		if matchedSnippets.isEmpty {
			// Find snippet in full transcript
			if let t = r.transcript {
				let tLower = t.lowercased()
				if let range = tLower.range(of: cleanQuery.lowercased()) {
					let start = t.index(range.lowerBound, offsetBy: -30, limitedBy: t.startIndex) ?? t.startIndex
					let end = t.index(range.upperBound, offsetBy: 60, limitedBy: t.endIndex) ?? t.endIndex
					matchedSnippets.append("...\"" + t[start..<end].replacingOccurrences(of: "\n", with: " ") + "\"...")
				}
			}
		}

		print("[\(r.noteId)] \(formatDate(r.createdAt)) | \(r.title) (\(formatDuration(r.durationSeconds)))")
		if matchedSnippets.isEmpty {
			print("      Matched Title: \(r.title)\n")
		} else {
			for snip in matchedSnippets.prefix(3) {
				print("      \(snip)")
			}
			print("")
		}
	}

	if untranscribedCount > 0 {
		print("Note: \(untranscribedCount) other recording(s) are not yet transcribed. Run `call-recordings sync` to index all recordings.")
	}
}

// MARK: - Audio Clipping & Excerpting

func clipCall(target: String, startTimeStr: String?, endTimeStr: String?, durationSec: Double?, matchWord: String?, padSec: Double?, outPath: String?) {
	let records = fetchCallRecords()
	guard let r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	guard let src = r.localAudioPath, FileManager.default.fileExists(atPath: src) else {
		fputs("Error: Master audio file not found on disk for call [\(r.noteId)].\n", stderr)
		exit(1)
	}

	let totalDuration = r.durationSeconds ?? 3600.0
	var finalStart: Double = 0.0
	var finalEnd: Double = min(totalDuration, 30.0)

	let padding = padSec ?? 6.0

	// If match word provided, locate matching segment
	if let match = matchWord, !match.isEmpty {
		var matched = false
		if let db = getTranscriptDB() {
			let sanitized = sanitizeFtsQuery(match)
			let matchSQL = "SELECT start_time, end_time FROM transcript_segments_fts WHERE note_id = ? AND transcript_segments_fts MATCH ? ORDER BY start_time ASC LIMIT 1;"
			var stmt: OpaquePointer?
			if sqlite3_prepare_v2(db, matchSQL, -1, &stmt, nil) == SQLITE_OK {
				sqlite3_bind_int64(stmt, 1, r.noteId)
				sqlite3_bind_text(stmt, 2, (sanitized as NSString).utf8String, -1, nil)
				if sqlite3_step(stmt) == SQLITE_ROW {
					let st = sqlite3_column_double(stmt, 0)
					let et = sqlite3_column_double(stmt, 1)
					finalStart = max(0.0, st - padding)
					finalEnd = min(totalDuration, et + padding)
					print("Matched \"\(match)\" at [\(formatTime(st)) - \(formatTime(et))].")
					matched = true
				}
				sqlite3_finalize(stmt)
			}
			sqlite3_close(db)
		}

		if !matched {
			let segs = getCachedSegments(noteId: r.noteId)
			if let found = segs.first(where: { $0.text.lowercased().contains(match.lowercased()) }) {
				finalStart = max(0.0, found.startTime - padding)
				finalEnd = min(totalDuration, found.endTime + padding)
				print("Matched \"\(match)\" at [\(formatTime(found.startTime)) - \(formatTime(found.endTime))].")
			} else {
				print("Notice: Word \"\(match)\" not found in segments. Using standard start/end.")
			}
		}
	}

	if let s = startTimeStr, let parsedS = parseTime(s) {
		finalStart = max(0.0, parsedS)
	}

	if let e = endTimeStr, let parsedE = parseTime(e) {
		finalEnd = min(totalDuration, parsedE)
	} else if let dur = durationSec {
		finalEnd = min(totalDuration, finalStart + dur)
	}

	if finalEnd <= finalStart {
		fputs("Error: End time (\(finalEnd)s) must be greater than start time (\(finalStart)s).\n", stderr)
		exit(1)
	}

	let df = DateFormatter()
	df.dateFormat = "yyyy-MM-dd"
	let safeTitle = r.title.replacingOccurrences(of: " ", with: "_").components(separatedBy: CharacterSet.alphanumerics.inverted.subtracting(CharacterSet(charactersIn: "_-"))).joined()
	let defaultFilename = "\(df.string(from: r.createdAt))_\(safeTitle)_\(r.noteId)_clip_\(formatTime(finalStart).replacingOccurrences(of: ":", with: "m"))s-\(formatTime(finalEnd).replacingOccurrences(of: ":", with: "m"))s.m4a"

	let destPath: String
	if let out = outPath {
		let expanded = (out as NSString).expandingTildeInPath
		var isDir: ObjCBool = false
		if FileManager.default.fileExists(atPath: expanded, isDirectory: &isDir) && isDir.boolValue {
			destPath = (expanded as NSString).appendingPathComponent(defaultFilename)
		} else {
			destPath = expanded
		}
	} else {
		let downloads = ("~/Downloads" as NSString).expandingTildeInPath
		destPath = (downloads as NSString).appendingPathComponent(defaultFilename)
	}

	try? FileManager.default.removeItem(atPath: destPath)

	print("Clipping [\(formatTime(finalStart)) -> \(formatTime(finalEnd))] (\(formatTime(finalEnd - finalStart))) from [\(r.noteId)] \(r.title)...")

	// Cut losslessly via ffmpeg passthrough if available, otherwise AVAssetExportSession
	let ffmpegBin = "/opt/homebrew/bin/ffmpeg"
	if FileManager.default.fileExists(atPath: ffmpegBin) {
		let proc = Process()
		proc.executableURL = URL(fileURLWithPath: ffmpegBin)
		proc.standardInput = FileHandle.nullDevice
		proc.arguments = [
			"-nostdin",
			"-ss", String(format: "%.2f", finalStart),
			"-to", String(format: "%.2f", finalEnd),
			"-i", src,
			"-c", "copy",
			destPath,
			"-y",
			"-loglevel", "error"
		]
		try? proc.run()
		proc.waitUntilExit()
		if proc.terminationStatus == 0 && FileManager.default.fileExists(atPath: destPath) {
			print("Exported audio clip to: \(destPath)")
			return
		}
	}

	// Fallback to AVAssetExportSession
	let asset = AVURLAsset(url: URL(fileURLWithPath: src))
	guard let session = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetPassthrough) else {
		fputs("Error: Could not initialize AVAssetExportSession.\n", stderr)
		exit(1)
	}
	session.outputURL = URL(fileURLWithPath: destPath)
	session.outputFileType = .m4a
	let startCM = CMTime(seconds: finalStart, preferredTimescale: 44100)
	let durCM = CMTime(seconds: finalEnd - finalStart, preferredTimescale: 44100)
	session.timeRange = CMTimeRange(start: startCM, duration: durCM)

	var done = false
	session.exportAsynchronously { done = true }
	let deadline = Date().addingTimeInterval(10.0)
	while !done && Date() < deadline {
		RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1))
	}

	if FileManager.default.fileExists(atPath: destPath) {
		print("Exported audio clip to: \(destPath)")
	} else {
		fputs("Error: Audio clipping failed.\n", stderr)
		exit(1)
	}
}

// MARK: - Sync & Backup

func syncCalls(backupDir: String?, force: Bool) {
	print("=== Call Recordings Sync & Backup ===")
	ensureLocalDatabase()
	let records = fetchCallRecords()
	print("Total recordings in Apple Notes: \(records.count)")

	var transcribedCount = 0
	for r in records {
		if force || r.transcript == nil || r.transcript!.isEmpty {
			guard let audioPath = r.localAudioPath else { continue }
			print("[\(r.noteId)] Transcribing \"\(r.title)\" (\(formatDuration(r.durationSeconds)))...", terminator: " ")
			fflush(stdout)
			if let res = transcribeAudio(filePath: audioPath, movPath: r.localMovPath, duration: r.durationSeconds, lang: nil) {
				saveCachedTranscript(
					noteId: r.noteId,
					noteUUID: r.noteUUID,
					mediaUUID: r.mediaUUID ?? "",
					title: r.title,
					dateStr: formatDate(r.createdAt),
					duration: r.durationSeconds ?? 0,
					transcript: res.transcript,
					segments: res.segments
				)
				transcribedCount += 1
				print("done.")
			} else {
				print("failed.")
			}
		}
	}

	let targetBackupBase: String
	if let custom = backupDir, !custom.isEmpty {
		targetBackupBase = (custom as NSString).expandingTildeInPath
	} else if let gdrive = resolveGoogleDriveDir() {
		targetBackupBase = ((gdrive as NSString).appendingPathComponent("call-recordings") as NSString).expandingTildeInPath
	} else {
		print("Notice: Google Drive mount not detected and no --backup-dir specified.")
		print("Transcriptions completed and saved to local SQLite database.")
		return
	}

	let audioDir = (targetBackupBase as NSString).appendingPathComponent("audio")
	try? FileManager.default.createDirectory(atPath: audioDir, withIntermediateDirectories: true, attributes: nil)

	var backedUpCount = 0
	let df = DateFormatter()
	df.dateFormat = "yyyy-MM-dd_HHmm"

	for r in records {
		guard let src = r.localAudioPath, FileManager.default.fileExists(atPath: src) else { continue }
		let dateStr = df.string(from: r.createdAt)
		let safeTitle = r.title.replacingOccurrences(of: " ", with: "_").components(separatedBy: CharacterSet.alphanumerics.inverted.subtracting(CharacterSet(charactersIn: "_-"))).joined()
		let destFilename = "\(dateStr)_\(safeTitle)_\(r.noteId).m4a"
		let destPath = (audioDir as NSString).appendingPathComponent(destFilename)

		if !FileManager.default.fileExists(atPath: destPath) {
			do {
				try FileManager.default.copyItem(atPath: src, toPath: destPath)
				backedUpCount += 1
			} catch {
				fputs("Error copying \(src) to \(destPath): \(error.localizedDescription)\n", stderr)
			}
		}
	}

	let destDBPath = (targetBackupBase as NSString).appendingPathComponent("transcripts.sqlite")
	var snapshotSuccess = false
	if let localDB = getTranscriptDB() {
		snapshotSuccess = backupDatabase(sourceDB: localDB, destPath: destDBPath)
		sqlite3_close(localDB)
	}

	print("")
	print("Summary:")
	print("  - Transcribed:       \(transcribedCount) new call(s)")
	print("  - Audio backed up:   \(backedUpCount) new audio file(s) -> \(audioDir)")
	print("  - Database snapshot: \(snapshotSuccess ? "Updated -> \(destDBPath)" : "Failed")")
	print("Sync complete.")
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

func playCall(target: String) {
	let records = fetchCallRecords()
	guard let r = records.first(where: { String($0.noteId) == target || $0.noteUUID == target || $0.title.lowercased().contains(target.lowercased()) }) else {
		fputs("Error: Call recording '\(target)' not found.\n", stderr)
		exit(1)
	}

	guard let path = r.localAudioPath, FileManager.default.fileExists(atPath: path) else {
		fputs("Error: Audio file not found on disk for note [\(r.noteId)].\n", stderr)
		exit(1)
	}

	print("Playing: [\(r.noteId)] \(r.title) (\(formatDuration(r.durationSeconds))) via afplay...")
	let proc = Process()
	proc.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
	proc.arguments = [path]
	try? proc.run()
	proc.waitUntilExit()
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
	call-recordings - CLI to access, transcribe, search, clip, and backup iPhone call recordings

	Usage:
	  call-recordings [list] [options]
	  call-recordings read <id|title> [-t|--transcribe] [--json]
	  call-recordings search "<query>" [-t|--transcribe]
	  call-recordings clip <id> [clip-options]
	  call-recordings sync [--backup-dir <dir>] [--force]
	  call-recordings transcribe <id|--all> [--lang <code>] [--force]
	  call-recordings export <id> [--out <dir|file>]
	  call-recordings play <id>
	  call-recordings open <id>

	Commands:
	  list          List call recordings with date, duration, size, and transcripts (default)
	  read          View full metadata, audio path, and timestamped/diarized transcript
	  search        FTS5 full-text search with Porter stemming across all calls and transcripts
	  clip          Cut lossless audio excerpts by timestamps or matching keyword to ~/Downloads
	  sync          Daily sync: transcribe new calls, backup audio and database snapshot to Google Drive
	  transcribe    Transcribe call recording audio locally via macOS Speech Neural Engine
	  export        Copy the master recording .m4a audio file to a folder or file path
	  play          Play the recording audio directly in terminal via native macOS afplay
	  open          Reveal and open the recording note in the macOS Notes application

	Clip Options:
	  --start <time>   Start timestamp in MM:SS (e.g. 01:30) or seconds (default: 00:00)
	  --end <time>     End timestamp in MM:SS (e.g. 02:00) or seconds
	  --duration <sec> Duration of clip from start (e.g. 20)
	  --match "<word>" Automatically locate matching spoken phrase and clip around it
	  --pad <sec>      Padding in seconds before and after match (default: 6s)
	  --out <path>     Destination folder or filepath (default: ~/Downloads)

	List & Filter Options:
	  --today       Filter to calls recorded today
	  --yesterday   Filter to calls recorded yesterday
	  --since <N>d  Filter to calls recorded in the last N days (e.g. --since 7d)
	  --limit <N>   Number of calls to list (default: 10)
	  --all         Include all call recordings (no limit)
	  --json        Output in structured JSON format

	Options:
	  -t, --transcribe Auto-transcribe recording on-the-fly if not already cached
	  --force          Force re-transcription or re-backup even if already cached
	  --lang <code>    Language code for speech recognition (e.g. en-US, es; default: en-US)
	  --backup-dir <d> Custom backup folder (defaults to Google Drive/call-recordings)
	  --out <path>     Output folder or filepath for export (default: current directory)
	  --help, -h       Show this help message

	Examples:
	  call-recordings
	  call-recordings list --today
	  call-recordings read 622 -t
	  call-recordings search "not allow"
	  call-recordings clip 622 --start 00:00 --end 00:22
	  call-recordings clip 622 --match "allow" --pad 8
	  call-recordings sync
	  call-recordings play 622
	"""
	print(usage)
}

func main() {
	ensureLocalDatabase()
	let args = CommandLine.arguments

	if args.count <= 1 || args.contains("--help") || args.contains("-h") {
		if args.count <= 1 {
			listCalls(limit: 10, includeAll: false, dateFilter: .none, jsonOutput: false)
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
		var dateFilter: DateFilter = .none
		var i = 2
		while i < args.count {
			if args[i] == "--limit" && i + 1 < args.count {
				limit = Int(args[i + 1])
				i += 1
			} else if args[i] == "--all" {
				includeAll = true
			} else if args[i] == "--json" {
				jsonOutput = true
			} else if args[i] == "--today" {
				dateFilter = .today
			} else if args[i] == "--yesterday" {
				dateFilter = .yesterday
			} else if args[i] == "--since" && i + 1 < args.count {
				let raw = args[i + 1].lowercased().replacingOccurrences(of: "d", with: "")
				if let d = Int(raw) {
					dateFilter = .sinceDays(d)
				}
				i += 1
			}
			i += 1
		}
		listCalls(limit: limit, includeAll: includeAll, dateFilter: dateFilter, jsonOutput: jsonOutput)

	case "read":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings read <id|title> [-t|--transcribe] [--json]\n", stderr)
			exit(1)
		}
		let target = args[2]
		let jsonOutput = args.contains("--json")
		let autoTranscribe = args.contains("-t") || args.contains("--transcribe")
		readCall(target: target, autoTranscribe: autoTranscribe, jsonOutput: jsonOutput)

	case "search":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings search \"<query>\" [-t|--transcribe]\n", stderr)
			exit(1)
		}
		let query = args[2]
		let autoTranscribe = args.contains("-t") || args.contains("--transcribe")
		searchCalls(query: query, autoTranscribe: autoTranscribe)

	case "clip":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings clip <id|title> [--start <time>] [--end <time>] [--match <word>] [--pad <sec>] [--out <dest>]\n", stderr)
			exit(1)
		}
		let target = args[2]
		var startTime: String? = nil
		var endTime: String? = nil
		var durationSec: Double? = nil
		var matchWord: String? = nil
		var padSec: Double? = nil
		var outPath: String? = nil
		var i = 3
		while i < args.count {
			if args[i] == "--start" && i + 1 < args.count {
				startTime = args[i + 1]
				i += 1
			} else if args[i] == "--end" && i + 1 < args.count {
				endTime = args[i + 1]
				i += 1
			} else if args[i] == "--duration" && i + 1 < args.count {
				durationSec = Double(args[i + 1])
				i += 1
			} else if args[i] == "--match" && i + 1 < args.count {
				matchWord = args[i + 1]
				i += 1
			} else if args[i] == "--pad" && i + 1 < args.count {
				padSec = Double(args[i + 1])
				i += 1
			} else if (args[i] == "--out" || args[i] == "-o") && i + 1 < args.count {
				outPath = args[i + 1]
				i += 1
			}
			i += 1
		}
		clipCall(target: target, startTimeStr: startTime, endTimeStr: endTime, durationSec: durationSec, matchWord: matchWord, padSec: padSec, outPath: outPath)

	case "sync":
		var backupDir: String? = nil
		var force = false
		var i = 2
		while i < args.count {
			if (args[i] == "--backup-dir" || args[i] == "-b") && i + 1 < args.count {
				backupDir = args[i + 1]
				i += 1
			} else if args[i] == "--force" {
				force = true
			}
			i += 1
		}
		syncCalls(backupDir: backupDir, force: force)

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

	case "play":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings play <id>\n", stderr)
			exit(1)
		}
		playCall(target: args[2])

	case "open":
		guard args.count >= 3 else {
			fputs("Usage: call-recordings open <id>\n", stderr)
			exit(1)
		}
		openCall(target: args[2])

	default:
		if Int(sub) != nil {
			let autoTranscribe = args.contains("-t") || args.contains("--transcribe")
			readCall(target: sub, autoTranscribe: autoTranscribe, jsonOutput: args.contains("--json"))
		} else {
			fputs("Unknown command: '\(sub)'. Run 'call-recordings --help' for usage.\n", stderr)
			exit(1)
		}
	}
}

main()
