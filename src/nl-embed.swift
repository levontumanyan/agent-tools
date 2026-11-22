import Foundation
import NaturalLanguage

func printHelp() {
	let help = """
	nl-embed — Generate 512-dim sentence embeddings using native macOS NaturalLanguage.

	USAGE:
		nl-embed "<text>"       Embed a single string and print JSON {"available": true, "dim": 512, "vector": [...]}
		nl-embed --batch        Read JSONL {"id": "...", "text": "..."} from stdin, write {"id": "...", "vector": [...]}
		nl-embed --check        Check if NLEmbedding.sentenceEmbedding(for: .english) is available
		nl-embed --help         Show this help message
	"""
	print(help)
}

func normalize(_ vec: [Double]) -> [Float] {
	var sumSq: Double = 0
	for v in vec {
		sumSq += v * v
	}
	let norm = sqrt(sumSq)
	if norm <= 0 {
		return vec.map { Float($0) }
	}
	return vec.map { Float($0 / norm) }
}

func embedText(_ embedding: NLEmbedding, _ text: String) -> [Float]? {
	let cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
	if cleaned.isEmpty {
		return nil
	}
	guard let vec = embedding.vector(for: cleaned) else {
		return nil
	}
	return normalize(vec)
}

func toJSONString(_ obj: Any) -> String {
	guard let data = try? JSONSerialization.data(withJSONObject: obj, options: []),
		  let str = String(data: data, encoding: .utf8) else {
		return "{}"
	}
	return str
}

let args = CommandLine.arguments
if args.contains("--help") || args.contains("-h") {
	printHelp()
	exit(0)
}

let embedding = NLEmbedding.sentenceEmbedding(for: .english)

if args.contains("--check") {
	if let emb = embedding {
		print(toJSONString(["available": true, "dim": emb.dimension]))
		exit(0)
	} else {
		print(toJSONString(["available": false, "dim": 0]))
		exit(0)
	}
}

if args.contains("--batch") {
	guard let emb = embedding else {
		while let line = readLine() {
			if let data = line.data(using: .utf8),
			   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
			   let id = obj["id"] {
				print(toJSONString(["id": id, "vector": NSNull()]))
			}
		}
		exit(0)
	}

	while let line = readLine() {
		let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
		if trimmed.isEmpty { continue }
		guard let data = trimmed.data(using: .utf8),
			  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
			  let id = obj["id"],
			  let text = obj["text"] as? String else {
			continue
		}
		if let vec = embedText(emb, text) {
			print(toJSONString(["id": id, "vector": vec]))
		} else {
			print(toJSONString(["id": id, "vector": NSNull()]))
		}
	}
	exit(0)
}

let positional = args.dropFirst().filter { !$0.hasPrefix("-") }
if positional.isEmpty {
	printHelp()
	exit(1)
}

let inputText = positional.joined(separator: " ")
guard let emb = embedding else {
	print(toJSONString(["available": false, "dim": 0, "vector": NSNull()]))
	exit(0)
}

if let vec = embedText(emb, inputText) {
	print(toJSONString(["available": true, "dim": emb.dimension, "vector": vec]))
} else {
	print(toJSONString(["available": true, "dim": emb.dimension, "vector": NSNull()]))
}
