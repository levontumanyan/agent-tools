SWIFT_SRCS := $(wildcard src/*.swift)
SWIFT_BINS := $(patsubst src/%.swift,bin/%,$(SWIFT_SRCS))

.PHONY: all build clean

all: build

build: $(SWIFT_BINS)

bin/%: src/%.swift
	@mkdir -p bin
	swiftc -O $< -o $@
	@grep -qxF "/$@" .gitignore || echo "/$@" >> .gitignore

clean:
	rm -f $(SWIFT_BINS)
