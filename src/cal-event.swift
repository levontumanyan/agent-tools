#!/usr/bin/env swift

import Foundation
import EventKit
import SQLite3

// ============================================================================
// cal-event: Fast CLI to add/query/edit/delete events via macOS EventKit
// Default Target: iCloud -> Home (or specified --calendar / --account)
// ============================================================================

enum Mode {
	case add
	case list
	case listCalendars
	case listSections
	case edit
	case delete
}

struct Config {
	var mode: Mode = .add
	var summary: String = ""
	var newTitle: String?
	var startDate: Date?
	var endDate: Date?
	var rangeStart: Date?
	var rangeEnd: Date?
	var durationMinutes: Int?
	var isAllDay: Bool?
	var calendarName: String?
	var accountName: String?
	var notes: String?
	var url: URL?
	var location: String?
	var alarmMinutesBefore: [Int]?
	var days: Int?
	var searchQuery: String?
	var showDetails: Bool = false
	var isReminder: Bool = false
	var includeAll: Bool = false
	var repeatFrequency: EKRecurrenceFrequency?
	var clearRecurrence: Bool = false
	var repeatInterval: Int = 1
	var repeatCount: Int?
	var repeatUntil: Date?
}

func printUsage() {
	let usage = """
	Usage:
	  cal-event add "<title>" [options]
	  cal-event add "<title>" --reminder [options]
	  cal-event edit "<query>" [options]
	  cal-event update "<query>" [options]
	  cal-event delete "<query>" [options]
	  cal-event list [options]
	  cal-event search "<query>" [options]
	  cal-event list-calendars [--reminder]
	  cal-event list-reminders [options]
	  cal-event list-sections [--calendar "<name>"]

	Target Defaults (for add):
	  Account:  iCloud
	  Calendar: Home (for events) / Default Reminders list (for reminders)

	List & Search Options:
	  --reminder, -r           Filter or operate on Apple Reminders instead of Calendar events
	  --all                    Include completed reminders (for list/search/delete/edit)
	  --from "<date/time>"     Start of range (default: start of today)
	  --to "<date/time>"       End of range (default: end of today, +N days, or +30 days for search)
	  --days <N>               Range in days from --from
	  --search, -s "<query>"   Filter by keyword in title, notes, or location
	  --calendar, -c "<name>"  Filter by calendar or reminder list name
	  --account, -a "<name>"   Filter by account/source name
	  --details, -v            Show notes, location, and URLs

	Add & Edit Options:
	  --reminder, -r           Create or manage as an Apple Reminder (appears in Calendar & Reminders)
	  --due "<date/time>"      Due date/time for reminder (alias for --start)
	  --title "<title>"         New event title (for edit/update)
	  --start "<date/time>"     Start date (e.g., "2026-09-09 09:00", "2026-09-09", "2026-09-09T09:00:00")
	  --end "<date/time>"       End date (optional)
	  --duration <minutes>      Duration in minutes (default: 30 for add)
	  --all-day                 Mark event or reminder as all-day
	  --repeat, -R "<freq>"    Repeat schedule: daily, weekly, monthly, yearly, "every 2 days", 2w, etc. (or none)
	  --count <N>              Number of repeat occurrences (e.g. --count 7)
	  --until "<date/time>"    End date for repetition
	  --calendar "<name>"       Target calendar or reminder list (for add; filter for search/edit/delete)
	  --account "<name>"        Target account/source (for add; filter for search/edit/delete)
	  --notes "<text>"          Event/reminder notes / description
	  --url "<url>"             Associated URL
	  --location "<text>"       Location string
	  --alarm <minutes>         Alarm minutes before event/due time (e.g., 60, or 60,1440; use -1 for none)
	  --from "<date/time>"      Search range start (for edit/delete)
	  --to "<date/time>"        Search range end (for edit/delete)
	  --list-calendars          List all available accounts & calendars

	Examples:
	  cal-event list
	  cal-event list --days 7
	  cal-event list --from "2026-09-12" --to "2026-09-15"
	  cal-event search "flight"
	  cal-event search "eggs" --reminder --all
	  cal-event search "LATAM" --details
	  cal-event add "Doctor Appointment" --start "2026-09-15 14:00" --duration 60 --alarm 60,1440
	  cal-event add "Daily Standup" --start "2026-09-15 09:30" --repeat daily
	  cal-event add "Team Sync" --start "2026-09-15 10:00" --repeat "every 2 weeks" --until "2026-12-31"
	  cal-event add "Take day off" --reminder --due "2026-10-14 08:00"
	  cal-event add "Buy bus ticket" --reminder --due "2026-10-13 09:00" --notes "Via WhatsApp +1234567890"
	  cal-event add "Apply Cream" --reminder --due "2026-11-01 16:00" --repeat daily --count 7
	  cal-event add "Groceries" --reminder --calendar "Grocery"
	  cal-event list-reminders
	  cal-event list --reminder
	  cal-event list-calendars --reminder
	  cal-event list-sections --calendar "Grocery"
	  cal-event edit "Doctor Appointment" --start "2026-09-15 15:30"
	  cal-event update "Doctor Appointment" --title "Dentist Appointment" --location "Dental Clinic"
	  cal-event update "Wallnut" --reminder --title "Walnuts 🌰" --calendar "Grocery"
	  cal-event delete "Doctor Appointment"
	  cal-event delete "Buy bus ticket" --reminder
	"""
	print(usage)
}

func parseRepeat(_ str: String) -> (frequency: EKRecurrenceFrequency?, interval: Int, clear: Bool)? {
	let lower = str.lowercased().trimmingCharacters(in: .whitespaces)
	if ["none", "never", "clear", "off"].contains(lower) {
		return (nil, 1, true)
	}

	var cleaned = lower
	if cleaned.hasPrefix("every ") {
		cleaned = String(cleaned.dropFirst(6)).trimmingCharacters(in: .whitespaces)
	}

	switch cleaned {
	case "day", "daily", "everyday":
		return (.daily, 1, false)
	case "week", "weekly":
		return (.weekly, 1, false)
	case "month", "monthly":
		return (.monthly, 1, false)
	case "year", "yearly", "annual", "annually":
		return (.yearly, 1, false)
	default:
		break
	}

	let regexShort = try? NSRegularExpression(pattern: "^(\\d+)\\s*([dwmy])$")
	if let match = regexShort?.firstMatch(in: cleaned, range: NSRange(cleaned.startIndex..., in: cleaned)) {
		if let numRange = Range(match.range(at: 1), in: cleaned),
		   let unitRange = Range(match.range(at: 2), in: cleaned),
		   let interval = Int(cleaned[numRange]), interval > 0 {
			let unit = String(cleaned[unitRange])
			switch unit {
			case "d": return (.daily, interval, false)
			case "w": return (.weekly, interval, false)
			case "m": return (.monthly, interval, false)
			case "y": return (.yearly, interval, false)
			default: break
			}
		}
	}

	let parts = cleaned.components(separatedBy: .whitespaces).filter { !$0.isEmpty }
	if parts.count == 2, let interval = Int(parts[0]), interval > 0 {
		let unit = parts[1]
		if unit.hasPrefix("day") {
			return (.daily, interval, false)
		} else if unit.hasPrefix("week") {
			return (.weekly, interval, false)
		} else if unit.hasPrefix("month") {
			return (.monthly, interval, false)
		} else if unit.hasPrefix("year") {
			return (.yearly, interval, false)
		}
	}

	return nil
}

func buildRecurrenceRule(config: Config) -> EKRecurrenceRule? {
	guard let freq = config.repeatFrequency else { return nil }
	var recEnd: EKRecurrenceEnd? = nil
	if let count = config.repeatCount, count > 0 {
		recEnd = EKRecurrenceEnd(occurrenceCount: count)
	} else if let until = config.repeatUntil {
		recEnd = EKRecurrenceEnd(end: until)
	}
	return EKRecurrenceRule(
		recurrenceWith: freq,
		interval: max(1, config.repeatInterval),
		end: recEnd
	)
}

func formatRecurrenceRule(_ rule: EKRecurrenceRule) -> String {
	var freqStr = ""
	switch rule.frequency {
	case .daily:
		freqStr = rule.interval == 1 ? "Daily" : "Every \(rule.interval) days"
	case .weekly:
		freqStr = rule.interval == 1 ? "Weekly" : "Every \(rule.interval) weeks"
	case .monthly:
		freqStr = rule.interval == 1 ? "Monthly" : "Every \(rule.interval) months"
	case .yearly:
		freqStr = rule.interval == 1 ? "Yearly" : "Every \(rule.interval) years"
	@unknown default:
		freqStr = "Recurring"
	}
	if let end = rule.recurrenceEnd {
		if end.occurrenceCount > 0 {
			freqStr += " (\(end.occurrenceCount) times)"
		} else if let endDate = end.endDate {
			let df = DateFormatter()
			df.dateStyle = .medium
			df.timeStyle = .none
			freqStr += " until \(df.string(from: endDate))"
		}
	}
	return freqStr
}

func parseDate(_ str: String, isEndOfDay: Bool = false) -> Date? {
	let trimmed = str.trimmingCharacters(in: .whitespaces)
	let onlyDateFormats = [
		"yyyy-MM-dd",
		"MM/dd/yyyy",
		"MMM d, yyyy"
	]

	let cal = Calendar.current
	let formatter = DateFormatter()
	formatter.locale = Locale(identifier: "en_US_POSIX")
	formatter.timeZone = TimeZone.current

	for format in onlyDateFormats {
		formatter.dateFormat = format
		if let date = formatter.date(from: trimmed) {
			if isEndOfDay {
				return cal.date(bySettingHour: 23, minute: 59, second: 59, of: date) ?? date
			} else {
				return cal.date(bySettingHour: 0, minute: 0, second: 0, of: date) ?? date
			}
		}
	}

	let formats = [
		"yyyy-MM-dd HH:mm:ss",
		"yyyy-MM-dd HH:mm",
		"yyyy-MM-dd'T'HH:mm:ss",
		"yyyy-MM-dd'T'HH:mm:ssZ",
		"MM/dd/yyyy HH:mm",
		"MMM d, yyyy h:mm a",
		"h:mm a",
		"ha"
	]

	for format in formats {
		formatter.dateFormat = format
		if let date = formatter.date(from: trimmed) {
			return date
		}
	}

	let isoFormatter = ISO8601DateFormatter()
	if let date = isoFormatter.date(from: trimmed) {
		return date
	}

	return nil
}

func handleAdd(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	if config.summary.isEmpty {
		fputs("Error: Missing event title.\n", stderr)
		exit(1)
	}

	let calName = config.calendarName ?? "Home"
	let accName = config.accountName ?? "iCloud"

	var matchedCal: EKCalendar? = allCalendars.first {
		$0.title.caseInsensitiveCompare(calName) == .orderedSame &&
		$0.source.title.caseInsensitiveCompare(accName) == .orderedSame
	}

	if matchedCal == nil {
		matchedCal = allCalendars.first {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame
		}
	}

	if matchedCal == nil && config.calendarName == nil {
		matchedCal = store.defaultCalendarForNewEvents ?? allCalendars.first
	}

	guard let targetCalendar = matchedCal else {
		fputs("Error: Calendar '\(calName)' (Account: '\(accName)') not found.\n", stderr)
		print("Run `cal-event list-calendars` to view available calendars.")
		exit(1)
	}

	let start = config.startDate ?? Date()
	let duration = config.durationMinutes ?? 30
	let end = config.endDate ?? start.addingTimeInterval(TimeInterval(duration * 60))
	let isAllDay = config.isAllDay ?? false
	let alarmList = config.alarmMinutesBefore ?? [0]

	let event = EKEvent(eventStore: store)
	event.title = config.summary
	event.startDate = start
	event.endDate = end
	event.isAllDay = isAllDay
	event.calendar = targetCalendar
	event.notes = config.notes
	event.url = config.url
	event.location = config.location

	for alarmMins in alarmList {
		let alarm = EKAlarm(relativeOffset: TimeInterval(-alarmMins * 60))
		event.addAlarm(alarm)
	}

	if let rule = buildRecurrenceRule(config: config) {
		event.addRecurrenceRule(rule)
	}

	do {
		let span: EKSpan = event.hasRecurrenceRules ? .futureEvents : .thisEvent
		try store.save(event, span: span)
		let df = DateFormatter()
		df.dateStyle = .medium
		df.timeStyle = isAllDay ? .none : .short
		print("✅ Event created successfully:")
		print("   • Title:    \(event.title ?? "")")
		print("   • When:     \(df.string(from: start)) - \(df.string(from: end))")
		print("   • Calendar: [\(targetCalendar.source.title)] -> \(targetCalendar.title)")
		if let rule = event.recurrenceRules?.first {
			print("   • Repeat:   \(formatRecurrenceRule(rule))")
		}
		if let loc = event.location, !loc.isEmpty {
			print("   • Location: \(loc)")
		}
		if !alarmList.isEmpty {
			let alarmStr = alarmList.map { "\($0)m before" }.joined(separator: ", ")
			print("   • Alarms:   \(alarmStr)")
		}
		if let notes = event.notes, !notes.isEmpty {
			print("   • Notes:    \(notes)")
		}
		if let url = event.url {
			print("   • Link:     \(url.absoluteString)")
		}
	} catch {
		fputs("Error saving event: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

func normalizeTitle(_ str: String) -> String {
	var s = ""
	for scalar in str.unicodeScalars {
		// filter out emoji and symbols
		if scalar.properties.isEmoji && scalar.value > 0x2380 {
			continue
		}
		s.append(Character(scalar))
	}
	let allowed = CharacterSet.alphanumerics.union(.whitespaces)
	return s.components(separatedBy: allowed.inverted).joined().lowercased().trimmingCharacters(in: .whitespaces)
}

func handleAddReminder(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	if config.summary.isEmpty {
		fputs("Error: Missing reminder title.\n", stderr)
		exit(1)
	}

	let targetCalendar: EKCalendar
	if let calName = config.calendarName {
		let matched = allCalendars.first {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame
		}
		guard let found = matched else {
			fputs("Error: Reminder list '\(calName)' not found.\n", stderr)
			print("Run `cal-event list-calendars --reminder` to view available lists.")
			exit(1)
		}
		targetCalendar = found
	} else {
		targetCalendar = store.defaultCalendarForNewReminders() ?? allCalendars.first!
	}

	// Deduplication / reactivation is strictly scoped to Grocery lists
	let isGroceryList = targetCalendar.title.caseInsensitiveCompare("Grocery") == .orderedSame || targetCalendar.title.caseInsensitiveCompare("Groceries") == .orderedSame
	let inputNorm = normalizeTitle(config.summary)
	var matchedExisting: EKReminder? = nil

	if isGroceryList && !inputNorm.isEmpty {
		let sem = DispatchSemaphore(value: 0)
		let predicate = store.predicateForReminders(in: [targetCalendar])
		store.fetchReminders(matching: predicate) { foundList in
			defer { sem.signal() }
			guard let foundList = foundList else { return }
			// 1. Prioritize active (incomplete) reminders first
			if let activeMatch = foundList.first(where: { !$0.isCompleted && normalizeTitle($0.title ?? "") == inputNorm }) {
				matchedExisting = activeMatch
				return
			}
			// 2. Fall back to completed reminders to reactivate
			if let completedMatch = foundList.first(where: { $0.isCompleted && normalizeTitle($0.title ?? "") == inputNorm }) {
				matchedExisting = completedMatch
				return
			}
		}
		sem.wait()
	}

	let reminder: EKReminder
	var wasReactivated = false

	if let existing = matchedExisting {
		reminder = existing
		if existing.isCompleted {
			existing.isCompleted = false
			existing.completionDate = nil
			wasReactivated = true
		} else {
			print("ℹ️ Reminder already active in [\(targetCalendar.title)]: \(existing.title ?? "")")
			// Update optional fields if provided
			var updated = false
			if let notes = config.notes, !notes.isEmpty {
				reminder.notes = notes
				updated = true
			}
			if let url = config.url {
				reminder.url = url
				updated = true
			}
			if updated {
				do {
					try store.save(reminder, commit: true)
					print("   Updated notes/details.")
				} catch {
					fputs("Error updating reminder: \(error.localizedDescription)\n", stderr)
				}
			}
			return
		}
	} else {
		reminder = EKReminder(eventStore: store)
		reminder.title = config.summary
		reminder.calendar = targetCalendar
	}

	if let notes = config.notes {
		reminder.notes = notes
	}
	if let url = config.url {
		reminder.url = url
	}

	let cal = Calendar.current
	if let start = config.startDate {
		if config.isAllDay == true {
			let comps = cal.dateComponents([.year, .month, .day], from: start)
			reminder.dueDateComponents = comps
			reminder.addAlarm(EKAlarm(absoluteDate: start))
		} else {
			let comps = cal.dateComponents([.year, .month, .day, .hour, .minute], from: start)
			reminder.dueDateComponents = comps
			reminder.addAlarm(EKAlarm(absoluteDate: start))
		}
	}

	if let alarmList = config.alarmMinutesBefore, !alarmList.isEmpty, let start = config.startDate {
		for alarmMins in alarmList {
			let alarmDate = start.addingTimeInterval(TimeInterval(-alarmMins * 60))
			reminder.addAlarm(EKAlarm(absoluteDate: alarmDate))
		}
	}

	if let rule = buildRecurrenceRule(config: config) {
		reminder.addRecurrenceRule(rule)
	}

	do {
		try store.save(reminder, commit: true)
		let df = DateFormatter()
		df.dateStyle = .medium
		df.timeStyle = (config.isAllDay == true) ? .none : .short
		if wasReactivated {
			print("🔁 Existing reminder reactivated (uncompleted):")
		} else {
			print("✅ Reminder created successfully (integrates into Calendar & Reminders):")
		}
		print("   • Title:    \(reminder.title ?? "")")
		if let due = config.startDate {
			print("   • Due Date: \(df.string(from: due))")
		}
		if let rule = reminder.recurrenceRules?.first {
			print("   • Repeat:   \(formatRecurrenceRule(rule))")
		}
		print("   • List:     [\(targetCalendar.source.title)] -> \(targetCalendar.title)")
		if let notes = reminder.notes, !notes.isEmpty {
			print("   • Notes:    \(notes)")
		}
		if let url = reminder.url {
			print("   • Link:     \(url.absoluteString)")
		}
	} catch {
		fputs("Error saving reminder: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

struct SectionInfo {
	let id: String
	let displayName: String
	var activeCount: Int = 0
	var completedCount: Int = 0
}

struct ReminderSectionsMap {
	var reminderToSection: [String: String] = [:]
	var orderedSections: [SectionInfo] = []
}

func loadSectionsForList(calendarName: String) -> ReminderSectionsMap? {
	let fileManager = FileManager.default
	let baseDir = fileManager.homeDirectoryForCurrentUser.appendingPathComponent("Library/Group Containers/group.com.apple.reminders/Container_v1/Stores")
	guard let contents = try? fileManager.contentsOfDirectory(at: baseDir, includingPropertiesForKeys: nil) else {
		return nil
	}
	let sqliteFiles = contents.filter { $0.pathExtension == "sqlite" }

	for dbUrl in sqliteFiles {
		var db: OpaquePointer?
		if sqlite3_open_v2(dbUrl.path, &db, SQLITE_OPEN_READONLY, nil) != SQLITE_OK {
			continue
		}
		defer { sqlite3_close(db) }

		var listStmt: OpaquePointer?
		let listSql = "SELECT Z_PK, cast(ZSECTIONIDSORDERINGASDATA as text), cast(ZMEMBERSHIPSOFREMINDERSINSECTIONSASDATA as text) FROM ZREMCDBASELIST WHERE ZNAME = ? COLLATE NOCASE LIMIT 1;"
		if sqlite3_prepare_v2(db, listSql, -1, &listStmt, nil) != SQLITE_OK {
			continue
		}
		sqlite3_bind_text(listStmt, 1, (calendarName as NSString).utf8String, -1, nil)

		guard sqlite3_step(listStmt) == SQLITE_ROW else {
			sqlite3_finalize(listStmt)
			continue
		}

		let listPK = sqlite3_column_int(listStmt, 0)
		var orderingJSON: String? = nil
		if let textPtr = sqlite3_column_text(listStmt, 1) {
			orderingJSON = String(cString: textPtr)
		}
		var membershipJSON: String? = nil
		if let textPtr = sqlite3_column_text(listStmt, 2) {
			membershipJSON = String(cString: textPtr)
		}
		sqlite3_finalize(listStmt)

		var secStmt: OpaquePointer?
		let secSql = "SELECT ZCKIDENTIFIER, ZDISPLAYNAME FROM ZREMCDBASESECTION WHERE ZLIST = ? AND (ZMARKEDFORDELETION = 0 OR ZMARKEDFORDELETION IS NULL);"
		var sectionsDict: [String: String] = [:]
		if sqlite3_prepare_v2(db, secSql, -1, &secStmt, nil) == SQLITE_OK {
			sqlite3_bind_int(secStmt, 1, listPK)
			while sqlite3_step(secStmt) == SQLITE_ROW {
				if let idPtr = sqlite3_column_text(secStmt, 0), let namePtr = sqlite3_column_text(secStmt, 1) {
					sectionsDict[String(cString: idPtr)] = String(cString: namePtr)
				}
			}
			sqlite3_finalize(secStmt)
		}

		if sectionsDict.isEmpty {
			return nil
		}

		var result = ReminderSectionsMap()

		if let mStr = membershipJSON, let mData = mStr.data(using: .utf8),
		   let mObj = try? JSONSerialization.jsonObject(with: mData) as? [String: Any],
		   let mList = mObj["memberships"] as? [[String: Any]] {
			for item in mList {
				if let mID = item["memberID"] as? String, let gID = item["groupID"] as? String, let sName = sectionsDict[gID] {
					result.reminderToSection[mID] = sName
				}
			}
		}

		var orderedIDs: [String] = []
		if let oStr = orderingJSON, let oData = oStr.data(using: .utf8),
		   let oObj = try? JSONSerialization.jsonObject(with: oData) as? [String: Any],
		   let oList = oObj["orderedIdentifiers"] as? [String] {
			orderedIDs = oList
		}

		var counts: [String: (active: Int, comp: Int)] = [:]
		var remStmt: OpaquePointer?
		let remSql = "SELECT ZCKIDENTIFIER, ZCOMPLETED FROM ZREMCDREMINDER WHERE ZLIST = ? AND (ZMARKEDFORDELETION = 0 OR ZMARKEDFORDELETION IS NULL);"
		if sqlite3_prepare_v2(db, remSql, -1, &remStmt, nil) == SQLITE_OK {
			sqlite3_bind_int(remStmt, 1, listPK)
			while sqlite3_step(remStmt) == SQLITE_ROW {
				if let idPtr = sqlite3_column_text(remStmt, 0) {
					let remID = String(cString: idPtr)
					let isComp = sqlite3_column_int(remStmt, 1) != 0
					if let secName = result.reminderToSection[remID] {
						var c = counts[secName] ?? (0, 0)
						if isComp { c.comp += 1 } else { c.active += 1 }
						counts[secName] = c
					}
				}
			}
			sqlite3_finalize(remStmt)
		}

		for sID in orderedIDs {
			if let name = sectionsDict[sID] {
				let c = counts[name] ?? (0, 0)
				result.orderedSections.append(SectionInfo(id: sID, displayName: name, activeCount: c.active, completedCount: c.comp))
			}
		}

		for (sID, name) in sectionsDict {
			if !orderedIDs.contains(sID) {
				let c = counts[name] ?? (0, 0)
				result.orderedSections.append(SectionInfo(id: sID, displayName: name, activeCount: c.active, completedCount: c.comp))
			}
		}

		return result
	}
	return nil
}

func handleListSections(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	let targetCalendars: [EKCalendar]
	if let calName = config.calendarName {
		let matched = allCalendars.filter { $0.title.caseInsensitiveCompare(calName) == .orderedSame }
		if matched.isEmpty {
			fputs("Error: Reminder list '\(calName)' not found.\n", stderr)
			exit(1)
		}
		targetCalendars = matched
	} else {
		targetCalendars = allCalendars
	}

	var foundAny = false
	for cal in targetCalendars {
		guard let secMap = loadSectionsForList(calendarName: cal.title), !secMap.orderedSections.isEmpty else {
			continue
		}
		foundAny = true
		print("Sections in [\(cal.title)] (\(secMap.orderedSections.count) cards):")
		for (i, sec) in secMap.orderedSections.enumerated() {
			var countStr = ""
			if sec.activeCount > 0 || sec.completedCount > 0 {
				countStr = " (\(sec.activeCount) active, \(sec.completedCount) completed)"
			} else {
				countStr = " (Empty)"
			}
			print("  \(i + 1). [\(sec.displayName)]\(countStr)")
		}
	}

	if !foundAny {
		if let calName = config.calendarName {
			print("No sections/cards found in list '\(calName)'.")
		} else {
			print("No sections/cards found in any reminder lists.")
		}
	}
}

func handleListReminders(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	let sem = DispatchSemaphore(value: 0)
	var targetCalendars: [EKCalendar]? = nil
	if let calName = config.calendarName {
		let matched = allCalendars.filter { $0.title.caseInsensitiveCompare(calName) == .orderedSame }
		if !matched.isEmpty { targetCalendars = matched }
	}

	let predicate: NSPredicate
	if config.includeAll {
		predicate = store.predicateForReminders(in: targetCalendars)
	} else {
		predicate = store.predicateForIncompleteReminders(withDueDateStarting: config.rangeStart, ending: config.rangeEnd, calendars: targetCalendars)
	}
	store.fetchReminders(matching: predicate) { reminders in
		defer { sem.signal() }
		guard var list = reminders, !list.isEmpty else {
			print("No reminders found.")
			return
		}

		if let query = config.searchQuery?.lowercased(), !query.isEmpty {
			list = list.filter { r in
				let titleMatch = r.title?.lowercased().contains(query) ?? false
				let notesMatch = r.notes?.lowercased().contains(query) ?? false
				return titleMatch || notesMatch
			}
		}

		if list.isEmpty {
			print("No reminders matching query.")
			return
		}

		var sectionsCache: [String: ReminderSectionsMap] = [:]
		for cal in (targetCalendars ?? allCalendars) {
			if let secMap = loadSectionsForList(calendarName: cal.title) {
				sectionsCache[cal.title.lowercased()] = secMap
			}
		}

		let df = DateFormatter()
		df.dateStyle = .medium
		df.timeStyle = .short
		print("Reminders (\(list.count) found):")
		for r in list {
			let calTitle = r.calendar.title
			var dueStr = "(No Due Date)"
			if let comps = r.dueDateComponents, let date = Calendar.current.date(from: comps) {
				dueStr = df.string(from: date)
			}
			let secName = sectionsCache[calTitle.lowercased()]?.reminderToSection[r.calendarItemIdentifier]
			let cardTag = secName != nil ? " [Card: \(secName!)]" : ""
			let statusTag = r.isCompleted ? " [Completed]" : ""
			let repTag = (r.recurrenceRules?.first != nil) ? " [\(formatRecurrenceRule(r.recurrenceRules!.first!))]" : ""
			print("  • [\(calTitle)] Due: \(dueStr) - \(r.title ?? "")\(repTag)\(cardTag)\(statusTag)")
			if config.showDetails, let notes = r.notes, !notes.isEmpty {
				print("    Notes: \(notes)")
			}
		}
	}
	sem.wait()
}

func handleDeleteReminder(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	guard let query = config.searchQuery?.trimmingCharacters(in: .whitespaces), !query.isEmpty else {
		fputs("Error: Missing search query for reminder to delete.\nUsage: cal-event delete \"<query>\" --reminder\n", stderr)
		exit(1)
	}

	let sem = DispatchSemaphore(value: 0)
	var targetCalendars: [EKCalendar]? = nil
	if let calName = config.calendarName {
		let matched = allCalendars.filter { $0.title.caseInsensitiveCompare(calName) == .orderedSame }
		if !matched.isEmpty { targetCalendars = matched }
	}

	let predicate: NSPredicate
	if config.includeAll {
		predicate = store.predicateForReminders(in: targetCalendars)
	} else {
		predicate = store.predicateForIncompleteReminders(withDueDateStarting: config.rangeStart, ending: config.rangeEnd, calendars: targetCalendars)
	}
	store.fetchReminders(matching: predicate) { reminders in
		defer { sem.signal() }
		guard var list = reminders, !list.isEmpty else {
			fputs("Error: No reminders found matching '\(query)'.\n", stderr)
			exit(1)
		}

		let q = query.lowercased()
		list = list.filter { r in
			let titleMatch = r.title?.lowercased().contains(q) ?? false
			let notesMatch = r.notes?.lowercased().contains(q) ?? false
			return titleMatch || notesMatch
		}

		if list.isEmpty {
			fputs("Error: No reminders found matching '\(query)'.\n", stderr)
			exit(1)
		}

		if list.count > 1 {
			fputs("Error: Multiple reminders (\(list.count)) matched '\(query)':\n", stderr)
			for r in list {
				let calTitle = r.calendar.title
				let title = r.title ?? "(No Title)"
				fputs("  • [\(calTitle)] \(title)\n", stderr)
			}
			fputs("Please refine your query or specify --calendar.\n", stderr)
			exit(1)
		}

		let reminder = list[0]
		do {
			try store.remove(reminder, commit: true)
			print("🗑️ Reminder deleted successfully:")
			print("   • Title: \(reminder.title ?? "")")
			print("   • List:  [\(reminder.calendar.source.title)] -> \(reminder.calendar.title)")
		} catch {
			fputs("Error deleting reminder: \(error.localizedDescription)\n", stderr)
			exit(1)
		}
	}
	sem.wait()
}

func handleEditReminder(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	guard let query = config.searchQuery?.trimmingCharacters(in: .whitespaces), !query.isEmpty else {
		fputs("Error: Missing search query for reminder to edit.\nUsage: cal-event edit \"<query>\" --reminder [options]\n", stderr)
		exit(1)
	}

	let sem = DispatchSemaphore(value: 0)
	var targetCalendars: [EKCalendar]? = nil
	if let calName = config.calendarName {
		let matched = allCalendars.filter { $0.title.caseInsensitiveCompare(calName) == .orderedSame }
		if !matched.isEmpty { targetCalendars = matched }
	}

	let predicate: NSPredicate
	if config.includeAll {
		predicate = store.predicateForReminders(in: targetCalendars)
	} else {
		predicate = store.predicateForIncompleteReminders(withDueDateStarting: config.rangeStart, ending: config.rangeEnd, calendars: targetCalendars)
	}
	store.fetchReminders(matching: predicate) { reminders in
		defer { sem.signal() }
		guard var list = reminders, !list.isEmpty else {
			fputs("Error: No reminders found matching '\(query)'.\n", stderr)
			exit(1)
		}

		let q = query.lowercased()
		list = list.filter { r in
			let titleMatch = r.title?.lowercased().contains(q) ?? false
			let notesMatch = r.notes?.lowercased().contains(q) ?? false
			return titleMatch || notesMatch
		}

		if list.isEmpty {
			fputs("Error: No reminders found matching '\(query)'.\n", stderr)
			exit(1)
		}

		if list.count > 1 {
			fputs("Error: Multiple reminders (\(list.count)) matched '\(query)':\n", stderr)
			for r in list {
				let calTitle = r.calendar.title
				let title = r.title ?? "(No Title)"
				fputs("  • [\(calTitle)] \(title)\n", stderr)
			}
			fputs("Please refine your query or specify --calendar.\n", stderr)
			exit(1)
		}

		let reminder = list[0]
		if let newTitle = config.newTitle {
			reminder.title = newTitle
		}
		if let notes = config.notes {
			reminder.notes = notes
		}
		if let url = config.url {
			reminder.url = url
		}
		if let start = config.startDate {
			let cal = Calendar.current
			if config.isAllDay == true {
				reminder.dueDateComponents = cal.dateComponents([.year, .month, .day], from: start)
			} else {
				reminder.dueDateComponents = cal.dateComponents([.year, .month, .day, .hour, .minute], from: start)
			}
		}

		if config.clearRecurrence {
			reminder.recurrenceRules = nil
		} else if let rule = buildRecurrenceRule(config: config) {
			reminder.recurrenceRules = [rule]
		}

		do {
			try store.save(reminder, commit: true)
			print("✅ Reminder updated successfully:")
			print("   • Title:  \(reminder.title ?? "")")
			print("   • List:   [\(reminder.calendar.source.title)] -> \(reminder.calendar.title)")
			if let rule = reminder.recurrenceRules?.first {
				print("   • Repeat: \(formatRecurrenceRule(rule))")
			}
		} catch {
			fputs("Error updating reminder: \(error.localizedDescription)\n", stderr)
			exit(1)
		}
	}
	sem.wait()
}

func handleList(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	let calendar = Calendar.current
	let now = Date()

	let start: Date
	if let userFrom = config.rangeStart {
		start = userFrom
	} else if let userStart = config.startDate {
		start = userStart
	} else {
		start = calendar.date(bySettingHour: 0, minute: 0, second: 0, of: now) ?? now
	}

	let end: Date
	if let userTo = config.rangeEnd {
		end = userTo
	} else if let userEnd = config.endDate {
		end = userEnd
	} else if let days = config.days {
		end = calendar.date(byAdding: .day, value: days, to: start) ?? start.addingTimeInterval(TimeInterval(days * 86400))
	} else if config.searchQuery != nil && config.startDate == nil && config.rangeStart == nil {
		// When searching without explicit dates, default to next 30 days
		end = calendar.date(byAdding: .day, value: 30, to: start) ?? start.addingTimeInterval(30 * 86400)
	} else if config.startDate != nil || config.rangeStart != nil {
		end = calendar.date(bySettingHour: 23, minute: 59, second: 59, of: start) ?? start.addingTimeInterval(86399)
	} else {
		end = calendar.date(bySettingHour: 23, minute: 59, second: 59, of: now) ?? now.addingTimeInterval(86399)
	}

	var targetCalendars: [EKCalendar]? = nil
	if let calName = config.calendarName, let accName = config.accountName {
		let matched = allCalendars.filter {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame &&
			$0.source.title.caseInsensitiveCompare(accName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	} else if let calName = config.calendarName {
		let matched = allCalendars.filter {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	} else if let accName = config.accountName {
		let matched = allCalendars.filter {
			$0.source.title.caseInsensitiveCompare(accName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	}

	let predicate = store.predicateForEvents(withStart: start, end: end, calendars: targetCalendars)
	var events = store.events(matching: predicate)

	if let query = config.searchQuery?.lowercased(), !query.isEmpty {
		events = events.filter { event in
			let titleMatch = event.title?.lowercased().contains(query) ?? false
			let notesMatch = event.notes?.lowercased().contains(query) ?? false
			let locationMatch = event.location?.lowercased().contains(query) ?? false
			return titleMatch || notesMatch || locationMatch
		}
	}

	events.sort { $0.startDate < $1.startDate }

	let rangeDf = DateFormatter()
	rangeDf.dateStyle = .medium
	rangeDf.timeStyle = .short

	if events.isEmpty {
		print("No events found between \(rangeDf.string(from: start)) and \(rangeDf.string(from: end)).")
		return
	}

	let dfDate = DateFormatter()
	dfDate.dateFormat = "yyyy-MM-dd"

	let dfTime = DateFormatter()
	dfTime.dateFormat = "HH:mm"

	let dfDateTime = DateFormatter()
	dfDateTime.dateFormat = "yyyy-MM-dd HH:mm"

	print("Events between \(rangeDf.string(from: start)) and \(rangeDf.string(from: end)) (\(events.count) found):")

	for event in events {
		let calSource = event.calendar.source.title
		let calTitle = event.calendar.title
		let timeStr: String

		if event.isAllDay {
			timeStr = "\(dfDate.string(from: event.startDate)) (All Day)"
		} else {
			let sameDay = calendar.isDate(event.startDate, inSameDayAs: event.endDate)
			if sameDay {
				timeStr = "\(dfDate.string(from: event.startDate)) \(dfTime.string(from: event.startDate)) - \(dfTime.string(from: event.endDate))"
			} else {
				timeStr = "\(dfDateTime.string(from: event.startDate)) - \(dfDateTime.string(from: event.endDate))"
			}
		}

		let title = event.title ?? "(No Title)"
		let locStr = (event.location != nil && !event.location!.isEmpty && !config.showDetails) ? " | Loc: \(event.location!)" : ""
		print("  • [\(calSource) -> \(calTitle)] \(timeStr): \(title)\(locStr)")

		if config.showDetails {
			if let loc = event.location, !loc.isEmpty {
				print("    Location: \(loc)")
			}
			if let url = event.url {
				print("    URL:      \(url.absoluteString)")
			}
			if let notes = event.notes, !notes.isEmpty {
				print("    Notes:")
				for line in notes.components(separatedBy: .newlines) {
					print("      \(line)")
				}
			}
		}
	}
}

func findMatchingEvents(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) -> [EKEvent] {
	guard let query = config.searchQuery?.trimmingCharacters(in: .whitespaces), !query.isEmpty else {
		return []
	}

	let calendar = Calendar.current
	let now = Date()

	let start = config.rangeStart ?? calendar.date(byAdding: .day, value: -30, to: now) ?? now.addingTimeInterval(-30 * 86400)
	let end = config.rangeEnd ?? calendar.date(byAdding: .day, value: 90, to: now) ?? now.addingTimeInterval(90 * 86400)

	var targetCalendars: [EKCalendar]? = nil
	if let calName = config.calendarName, let accName = config.accountName {
		let matched = allCalendars.filter {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame &&
			$0.source.title.caseInsensitiveCompare(accName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	} else if let calName = config.calendarName {
		let matched = allCalendars.filter {
			$0.title.caseInsensitiveCompare(calName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	} else if let accName = config.accountName {
		let matched = allCalendars.filter {
			$0.source.title.caseInsensitiveCompare(accName) == .orderedSame
		}
		if !matched.isEmpty { targetCalendars = matched }
	}

	let predicate = store.predicateForEvents(withStart: start, end: end, calendars: targetCalendars)
	var events = store.events(matching: predicate)

	let lowerQuery = query.lowercased()
	events = events.filter { event in
		let titleMatch = event.title?.lowercased().contains(lowerQuery) ?? false
		let notesMatch = event.notes?.lowercased().contains(lowerQuery) ?? false
		let locationMatch = event.location?.lowercased().contains(lowerQuery) ?? false
		return titleMatch || notesMatch || locationMatch
	}

	events.sort { $0.startDate < $1.startDate }
	return events
}

func formatEventTime(_ event: EKEvent) -> String {
	let calendar = Calendar.current
	let dfDate = DateFormatter()
	dfDate.dateFormat = "yyyy-MM-dd"
	let dfTime = DateFormatter()
	dfTime.dateFormat = "HH:mm"
	let dfDateTime = DateFormatter()
	dfDateTime.dateFormat = "yyyy-MM-dd HH:mm"

	if event.isAllDay {
		return "\(dfDate.string(from: event.startDate)) (All Day)"
	} else if calendar.isDate(event.startDate, inSameDayAs: event.endDate) {
		return "\(dfDate.string(from: event.startDate)) \(dfTime.string(from: event.startDate)) - \(dfTime.string(from: event.endDate))"
	} else {
		return "\(dfDateTime.string(from: event.startDate)) - \(dfDateTime.string(from: event.endDate))"
	}
}

func handleEdit(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	guard let query = config.searchQuery?.trimmingCharacters(in: .whitespaces), !query.isEmpty else {
		fputs("Error: Missing search query for event to edit.\nUsage: cal-event edit \"<query>\" [options]\n", stderr)
		exit(1)
	}

	let events = findMatchingEvents(config: config, store: store, allCalendars: allCalendars)

	if events.isEmpty {
		fputs("Error: No events found matching '\(query)'.\n", stderr)
		exit(1)
	}

	if events.count > 1 {
		fputs("Error: Multiple events (\(events.count)) matched '\(query)':\n", stderr)
		for event in events {
			let calSource = event.calendar.source.title
			let calTitle = event.calendar.title
			let title = event.title ?? "(No Title)"
			fputs("  • [\(calSource) -> \(calTitle)] \(formatEventTime(event)): \(title)\n", stderr)
		}
		fputs("Please refine your query with --from, --to, --calendar, or a more specific title.\n", stderr)
		exit(1)
	}

	let event = events[0]

	if let newTitle = config.newTitle, !newTitle.isEmpty {
		event.title = newTitle
	}

	if let newStart = config.startDate {
		let origDuration = event.endDate.timeIntervalSince(event.startDate)
		event.startDate = newStart
		if let newEnd = config.endDate {
			event.endDate = newEnd
		} else if let duration = config.durationMinutes {
			event.endDate = newStart.addingTimeInterval(TimeInterval(duration * 60))
		} else {
			event.endDate = newStart.addingTimeInterval(origDuration > 0 ? origDuration : 1800)
		}
	} else if let newEnd = config.endDate {
		event.endDate = newEnd
	} else if let duration = config.durationMinutes {
		event.endDate = event.startDate.addingTimeInterval(TimeInterval(duration * 60))
	}

	if let isAllDay = config.isAllDay {
		event.isAllDay = isAllDay
	}

	if let location = config.location {
		event.location = location
	}

	if let notes = config.notes {
		event.notes = notes
	}

	if let url = config.url {
		event.url = url
	}

	if let alarmMinsList = config.alarmMinutesBefore {
		if let existingAlarms = event.alarms {
			for a in existingAlarms {
				event.removeAlarm(a)
			}
		}
		for mins in alarmMinsList {
			event.addAlarm(EKAlarm(relativeOffset: TimeInterval(-mins * 60)))
		}
	}

	if config.clearRecurrence {
		event.recurrenceRules = nil
	} else if let rule = buildRecurrenceRule(config: config) {
		event.recurrenceRules = [rule]
	}

	do {
		let span: EKSpan = event.hasRecurrenceRules ? .futureEvents : .thisEvent
		try store.save(event, span: span)
		let df = DateFormatter()
		df.dateStyle = .medium
		df.timeStyle = event.isAllDay ? .none : .short
		print("✅ Event updated successfully:")
		print("   • Title:    \(event.title ?? "")")
		print("   • When:     \(df.string(from: event.startDate)) - \(df.string(from: event.endDate))")
		print("   • Calendar: [\(event.calendar.source.title)] -> \(event.calendar.title)")
		if let rule = event.recurrenceRules?.first {
			print("   • Repeat:   \(formatRecurrenceRule(rule))")
		}
		if let loc = event.location, !loc.isEmpty {
			print("   • Location: \(loc)")
		}
		if let alarms = event.alarms, !alarms.isEmpty {
			let alarmStr = alarms.map { "\(Int(-$0.relativeOffset / 60))m before" }.joined(separator: ", ")
			print("   • Alarms:   \(alarmStr)")
		}
		if let notes = event.notes, !notes.isEmpty {
			print("   • Notes:    \(notes)")
		}
		if let url = event.url {
			print("   • Link:     \(url.absoluteString)")
		}
	} catch {
		fputs("Error saving event: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

func handleDelete(config: Config, store: EKEventStore, allCalendars: [EKCalendar]) {
	guard let query = config.searchQuery?.trimmingCharacters(in: .whitespaces), !query.isEmpty else {
		fputs("Error: Missing search query for event to delete.\nUsage: cal-event delete \"<query>\" [options]\n", stderr)
		exit(1)
	}

	let events = findMatchingEvents(config: config, store: store, allCalendars: allCalendars)

	if events.isEmpty {
		fputs("Error: No events found matching '\(query)'.\n", stderr)
		exit(1)
	}

	if events.count > 1 {
		fputs("Error: Multiple events (\(events.count)) matched '\(query)':\n", stderr)
		for event in events {
			let calSource = event.calendar.source.title
			let calTitle = event.calendar.title
			let title = event.title ?? "(No Title)"
			fputs("  • [\(calSource) -> \(calTitle)] \(formatEventTime(event)): \(title)\n", stderr)
		}
		fputs("Please refine your query with --from, --to, --calendar, or a more specific title.\n", stderr)
		exit(1)
	}

	let event = events[0]
	let title = event.title ?? "(No Title)"
	let timeStr = formatEventTime(event)
	let calStr = "[\(event.calendar.source.title)] -> \(event.calendar.title)"

	do {
		try store.remove(event, span: .thisEvent)
		print("🗑️ Event deleted successfully:")
		print("   • Title:    \(title)")
		print("   • When:     \(timeStr)")
		print("   • Calendar: \(calStr)")
	} catch {
		fputs("Error deleting event: \(error.localizedDescription)\n", stderr)
		exit(1)
	}
}

func main() {
	var args = CommandLine.arguments
	args.removeFirst()

	if args.isEmpty || args.contains("-h") || args.contains("--help") {
		printUsage()
		exit(0)
	}

	var config = Config()

	if args[0] == "list-calendars" || args.contains("--list-calendars") {
		config.mode = .listCalendars
		args.removeFirst()
	} else if args[0] == "list-sections" || args[0] == "sections" || args[0] == "cards" {
		config.mode = .listSections
		config.isReminder = true
		args.removeFirst()
	} else if args[0] == "list-reminders" || args[0] == "reminders" {
		config.mode = .list
		config.isReminder = true
		args.removeFirst()
	} else if args[0] == "list" || args[0] == "ls" || args[0] == "query" {
		config.mode = .list
		args.removeFirst()
	} else if args[0] == "search" || args[0] == "find" {
		config.mode = .list
		args.removeFirst()
		if !args.isEmpty && !args[0].hasPrefix("-") {
			config.searchQuery = args.removeFirst()
		}
	} else if args[0] == "edit" || args[0] == "update" {
		config.mode = .edit
		args.removeFirst()
		if !args.isEmpty && !args[0].hasPrefix("-") {
			config.searchQuery = args.removeFirst()
		}
	} else if args[0] == "delete" || args[0] == "rm" || args[0] == "remove" {
		config.mode = .delete
		args.removeFirst()
		if !args.isEmpty && !args[0].hasPrefix("-") {
			config.searchQuery = args.removeFirst()
		}
	} else if args[0] == "add" {
		config.mode = .add
		args.removeFirst()
		if !args.isEmpty && !args[0].hasPrefix("-") {
			config.summary = args.removeFirst()
		}
	} else if !args[0].hasPrefix("-") {
		config.mode = .add
		config.summary = args.removeFirst()
	}

	var idx = 0
	while idx < args.count {
		let arg = args[idx]
		switch arg {
		case "--title", "--new-title":
			if idx + 1 < args.count {
				idx += 1
				config.newTitle = args[idx]
			}
		case "--start":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: false) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.startDate = d
			}
		case "--from":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: false) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.rangeStart = d
			}
		case "--end":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: true) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.endDate = d
			}
		case "--to":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: true) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.rangeEnd = d
			}
		case "--duration":
			if idx + 1 < args.count {
				idx += 1
				if let mins = Int(args[idx]) {
					config.durationMinutes = mins
				}
			}
		case "--days":
			if idx + 1 < args.count {
				idx += 1
				if let d = Int(args[idx]) {
					config.days = d
				}
			}
		case "--search", "-s":
			if idx + 1 < args.count {
				idx += 1
				config.searchQuery = args[idx]
			}
		case "--details", "-v":
			config.showDetails = true
		case "--all-day":
			config.isAllDay = true
		case "--calendar", "-c":
			if idx + 1 < args.count {
				idx += 1
				config.calendarName = args[idx]
			}
		case "--account", "-a":
			if idx + 1 < args.count {
				idx += 1
				config.accountName = args[idx]
			}
		case "--notes", "-n":
			if idx + 1 < args.count {
				idx += 1
				config.notes = args[idx]
			}
		case "--url":
			if idx + 1 < args.count {
				idx += 1
				config.url = URL(string: args[idx])
			}
		case "--location", "-l":
			if idx + 1 < args.count {
				idx += 1
				config.location = args[idx]
			}
		case "--alarm":
			if idx + 1 < args.count {
				idx += 1
				let rawAlarms = args[idx]
				if rawAlarms == "-1" {
					config.alarmMinutesBefore = []
				} else {
					let parts = rawAlarms.split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
					if !parts.isEmpty {
						config.alarmMinutesBefore = parts.filter { $0 >= 0 }
					}
				}
			}
		case "--all":
			config.includeAll = true
		case "--reminder", "-r":
			config.isReminder = true
		case "--due":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: false) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.startDate = d
			}
		case "--repeat", "--recurrence", "-R":
			if idx + 1 < args.count {
				idx += 1
				guard let parsed = parseRepeat(args[idx]) else {
					fputs("Error: Invalid repeat value '\(args[idx])'. Use daily, weekly, monthly, yearly, 'every 2 days', 2w, or none.\n", stderr)
					exit(1)
				}
				config.repeatFrequency = parsed.frequency
				config.repeatInterval = parsed.interval
				config.clearRecurrence = parsed.clear
			}
		case "--count":
			if idx + 1 < args.count {
				idx += 1
				if let val = Int(args[idx]), val > 0 {
					config.repeatCount = val
				} else {
					fputs("Error: Invalid count '\(args[idx])'. Must be a positive integer.\n", stderr)
					exit(1)
				}
			}
		case "--until":
			if idx + 1 < args.count {
				idx += 1
				guard let d = parseDate(args[idx], isEndOfDay: true) else {
					fputs("Error: Could not parse date '\(args[idx])'.\n", stderr)
					exit(1)
				}
				config.repeatUntil = d
			}
		default:
			break
		}
		idx += 1
	}

	let store = EKEventStore()
	let semaphore = DispatchSemaphore(value: 0)

	if config.isReminder {
		if #available(macOS 14.0, *) {
			store.requestFullAccessToReminders { granted, error in
				defer { semaphore.signal() }

				guard granted else {
					fputs("Error: Reminders access not granted. Please check macOS Privacy & Security settings.\n", stderr)
					exit(1)
				}

				let allReminderLists = store.calendars(for: .reminder)

				if config.mode == .listCalendars {
					print("Available Reminder Lists:")
					for cal in allReminderLists {
						print("  • Account: [\(cal.source.title)] -> List: [\(cal.title)]")
					}
					return
				}

				if config.mode == .listSections {
					handleListSections(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .list {
					handleListReminders(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .delete {
					handleDeleteReminder(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .edit {
					handleEditReminder(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				handleAddReminder(config: config, store: store, allCalendars: allReminderLists)
			}
		} else {
			store.requestAccess(to: .reminder) { granted, error in
				defer { semaphore.signal() }

				guard granted else {
					fputs("Error: Reminders access not granted. Please check macOS Privacy & Security settings.\n", stderr)
					exit(1)
				}

				let allReminderLists = store.calendars(for: .reminder)

				if config.mode == .listCalendars {
					print("Available Reminder Lists:")
					for cal in allReminderLists {
						print("  • Account: [\(cal.source.title)] -> List: [\(cal.title)]")
					}
					return
				}

				if config.mode == .listSections {
					handleListSections(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .list {
					handleListReminders(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .delete {
					handleDeleteReminder(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				if config.mode == .edit {
					handleEditReminder(config: config, store: store, allCalendars: allReminderLists)
					return
				}

				handleAddReminder(config: config, store: store, allCalendars: allReminderLists)
			}
		}

		semaphore.wait()
		return
	}

	store.requestFullAccessToEvents { granted, error in
		defer { semaphore.signal() }

		guard granted else {
			fputs("Error: Calendar access not granted. Please check macOS Privacy & Security settings.\n", stderr)
			exit(1)
		}

		let allCalendars = store.calendars(for: .event)

		if config.mode == .listCalendars {
			print("Available Calendars:")
			for cal in allCalendars {
				print("  • Account: [\(cal.source.title)] -> Calendar: [\(cal.title)]")
			}
			return
		}

		if config.mode == .list {
			handleList(config: config, store: store, allCalendars: allCalendars)
			return
		}

		if config.mode == .edit {
			handleEdit(config: config, store: store, allCalendars: allCalendars)
			return
		}

		if config.mode == .delete {
			handleDelete(config: config, store: store, allCalendars: allCalendars)
			return
		}

		handleAdd(config: config, store: store, allCalendars: allCalendars)
	}

	semaphore.wait()
}

main()
