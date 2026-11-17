#!/usr/bin/env python3
"""Check that a handoff block pastes cleanly after a command, and fits the handoff cap.

Usage: check_block.py <file>   (or the block on stdin). Prints one line per problem and exits 1 if any.
A command accepts file @-mentions (@ and an absolute path to an existing file) and rejects any other
@-mention, slash command, link or inline formatting. A bare file name like log.md or x.py reads as a link.
"""
import os
import re
import sys

MAX_LINES, MAX_WORDS = 40, 450
DOTTED = re.compile(r"[A-Za-z0-9_-]\.[A-Za-z]{2,}")  # log.md, delegate.py, release.repos, example.com
EDGE = "\"'(),;:.!?"


def problems(text):
    found = []
    lines = text.strip("\n").splitlines()
    if len(lines) > MAX_LINES:
        found.append(f"{len(lines)} lines; the cap is {MAX_LINES}")
    if len(text.split()) > MAX_WORDS:
        found.append(f"{len(text.split())} words; the cap is {MAX_WORDS}")
    for n, line in enumerate(lines, 1):
        for mark, why in (("`", "backtick"), ("**", "bold"), ("__", "underline"), ("~~", "strikethrough"),
                          ("](", "markdown link"), ("<", "angle bracket"), (">", "angle bracket")):
            if mark in line:
                found.append(f"line {n}: {why} ({mark})")
        if re.match(r"\s*#", line):
            found.append(f"line {n}: heading (#)")
        if re.search(r"(^|\s)[*_]\S|\S[*_](\s|$)", line):
            found.append(f"line {n}: emphasis marker (* or _ at a word edge)")
        for word in line.split():
            bare = word.strip(EDGE)
            if word.startswith("@"):
                path = bare.lstrip("@")
                if word != word.rstrip(EDGE):
                    found.append(f"line {n}: {word} has punctuation touching the @-mention; put a space after it")
                if not path.startswith("/"):
                    found.append(f"line {n}: {word} is not a file @-mention; use @ and an absolute path")
                elif not os.path.isfile(path):
                    found.append(f"line {n}: {word} names no existing file")
            elif "://" in word or bare.startswith("www."):
                found.append(f"line {n}: {bare} is a link")
            elif bare.startswith("/"):
                found.append(f"line {n}: {bare} starts with / and reads as a slash command")
            elif DOTTED.search(bare):
                found.append(f"line {n}: {bare} reads as a link; make it a file @-mention or say it in words")
    return found


def main():
    text = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    found = problems(text)
    print("\n".join(found) if found else "ok")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
