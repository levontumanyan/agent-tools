SWIFT_SRCS := $(wildcard src/*.swift)
SWIFT_BINS := $(patsubst src/%.swift,bin/%,$(SWIFT_SRCS))

.PHONY: all build clean

all: build

build: $(SWIFT_BINS) bin/antigravity-shipper

bin/%: src/%.swift
	@mkdir -p bin
	swiftc -O $< -o $@
	@grep -qxF "/$@" .gitignore || echo "/$@" >> .gitignore

bin/antigravity-shipper: $(wildcard src/antigravity-shipper/*.go) src/antigravity-shipper/go.mod
	@mkdir -p bin
	go -C src/antigravity-shipper build -o ../../bin/antigravity-shipper .
	@grep -qxF "/$@" .gitignore || echo "/$@" >> .gitignore

clean:
	rm -f $(SWIFT_BINS) bin/antigravity-shipper
