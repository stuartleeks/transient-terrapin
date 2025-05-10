from dataclasses import dataclass
import hashlib
import os
import re
import time
from typing import Iterable
import requests
import subprocess
import sys
import yaml

#
# Import the path list specified in FILTER_FILE into a data structure.
# This is a YAML file in the following format:
#
# name: <filter_name>
# files:
#   - <path regex>
#   - <path regex>
#   - <path regex>
# skip-if:
#   all-files-match-any:
#     - <path regex>
#     - <path regex>
#
# The files property is required, the skip-if section is optional.
#


# TODO - split this to share filter definitions with other scripts

class PathFilter:
    def __init__(self, expression: str):
        self.expression = expression
        self._regex = None

    @property
    def regex(self):
        if self._regex is None:
            self._regex = re.compile(self.expression)
        return self._regex


class SkipIf:
    all_file_match_any: list[PathFilter] | None = None

    def __init__(self, all_file_match_any: list[str] | None = None):
        if all_file_match_any is not None:
            self.all_file_match_any = [
                PathFilter(e) for e in all_file_match_any]


class Filter:
    name: str
    files: list[PathFilter]
    skip_if: SkipIf | None = None

    def __init__(self, name: str, files: list[str], skip_if: SkipIf | None = None):
        self.name = name
        self.files = [PathFilter(e) for e in files]
        self.skip_if = skip_if

    def is_match_for_file(self, file: str) -> bool:
        """
        Check if the file matches any of the filters
        """
        for path_filter in self.files:
            if path_filter.regex.match(file):
                return True
        return False

    def is_match(self, files: Iterable[str]) -> bool:
        match = False
        allFilesMatchAnySkip = (
            self.skip_if is not None and self.skip_if.all_file_match_any is not None
        )
        for file in files:
            if not match:  # only check for a match if we haven't found one yet
                if self.is_match_for_file(file):
                    match = True
                    break

            if (
                allFilesMatchAnySkip
            ):  # only check for skip if we haven't already had a non-match
                for path_filter in self.skip_if.all_file_match_any:
                    if not path_filter.regex.match(file):
                        allFilesMatchAnySkip = False
                        break
        result = match and not allFilesMatchAnySkip
        return result

    def calculate_hash(self, files: Iterable[str]) -> str:
        """
        Calculate the fingerprint based on the files that match the filter

        NOTE: to get a stable fingerprint, ensure a consistent order of files
        """

        os.makedirs(".hash-debug", exist_ok=True)
        with open(os.path.join(".hash-debug", f"{self.name}.txt"), "w") as debug_file:

            print(f"::group::Filter - {self.name}", flush=True) 


            # iterate the files in the file_list and calculate the sha1 hash
            hash = hashlib.sha1()

            for file in files:
                for path_filter in self.files:
                    if path_filter.regex.match(file):
                        # print(f"Adding {file} to hash", flush=True)
                        # Add the filename to the hash
                        hash.update(file.encode("utf-8"))
                        debug_file.write(f"{file}\n")
                        print(file=file, flush=True)

                        with open(file, "rb") as f:
                            # Read the file in chunks to handle large files
                            for chunk in iter(lambda: f.read(4096), b""):
                                hash.update(chunk)
                        break

            hash_result = hash.hexdigest()
            debug_file.write(f"\nHash: {hash_result}\n")
            print("::endgroup::", flush=True)
            print(f"Hash (${self.name}): {hash_result}", flush=True)
            return hash_result


def load_filter_file(filter_file: str) -> list[Filter]:
    with open(filter_file, "r") as f:
        filter_data = yaml.safe_load(f)
    if filter_data is None:
        print(f"Filter file {filter_file} is empty.", flush=True)
        sys.exit(1)
    if not isinstance(filter_data, list):
        print(f"Filter file {filter_file} is not a list.", flush=True)
        sys.exit(1)

    filters = []
    for filter_item in filter_data:
        if "name" not in filter_item:
            print(
                f"Filter file {filter_file} does not contain a name.", flush=True)
            sys.exit(1)
        if "files" not in filter_item:
            print(
                f"Filter file {filter_file} does not contain a files list.", flush=True)
            sys.exit(1)
        if not isinstance(filter_item["files"], list):
            print(
                f"Filter file {filter_file} files list is not a list.", flush=True)
            sys.exit(1)
        if len(filter_item["files"]) == 0:
            print(
                f"Filter file {filter_file} files list is empty.", flush=True)
            sys.exit(1)

        skip_if = None
        if "skip-if" in filter_item:
            if "all-files-match-any" in filter_item["skip-if"]:
                skip_if = SkipIf(filter_item["skip-if"]["all-files-match-any"])

        filter = Filter(
            name=filter_item["name"],
            files=filter_item["files"],
            skip_if=skip_if,
        )
        filters.append(filter)

    return filters


def recursive_file_list(path: str) -> Iterable[str]:
    for root, dirnames, files in os.walk(path, topdown=True):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for file in sorted(files):
            yield os.path.relpath(os.path.join(root, file), path)


def set_github_output(name: str, value: str):
    if os.getenv("GITHUB_OUTPUT") is None:
        print("GITHUB_OUTPUT environment variable is not set.", flush=True)
        sys.exit(1)

    with open(os.getenv("GITHUB_OUTPUT"), "a") as f:
        f.write(f"{name}={value}\n")
    # print(f"OUTPUT:{name}={value}", flush=True)


def set_github_env(name: str, value: str):
    if os.getenv("GITHUB_ENV") is None:
        print("GITHUB_ENV environment variable is not set.", flush=True)
        sys.exit(1)

    with open(os.getenv("GITHUB_ENV"), "a") as f:
        f.write(f"{name}={value}\n")
    # print(f"OUTPUT:{name}={value}", flush=True)

def write_to_step_summary(message: str):
    if os.getenv("GITHUB_STEP_SUMMARY") is None:
        print("GITHUB_STEP_SUMMARY environment variable is not set.", flush=True)
        sys.exit(1)

    with open(os.getenv("GITHUB_STEP_SUMMARY"), "a") as f:
        f.write(f"{message}\n")

if __name__ == "__main__":
    if not os.path.exists(".hashes"):
        os.mkdir(".hashes")

    filter_file = os.getenv("FILTER_FILE")
    if filter_file is None:
        print("FILTER_FILE environment variable is not set.", flush=True)
        sys.exit(1)
    if not os.path.exists(filter_file):
        print(f"Filter file {filter_file} does not exist.", flush=True)
        sys.exit(1)

    filters = load_filter_file(filter_file)
    print(
        f"Loaded filter file {filter_file} with filters {[f.name for f in filters]}", flush=True)

    write_to_step_summary("\n|Filter|Hash| Cached|\n|---|---|---|")

    for filter in filters:
        filter_var_name = f"FILTER_{filter.name.upper()}"
        filter_var_value = os.getenv(filter_var_name, None)
        if filter_var_value is None:
            print(f"{filter_var_name} environment variable is not set.", flush=True)
            sys.exit(1)
        hash_file = os.path.join(".hashes", f"{filter.name}.hash")
        if filter_var_value.lower() != "true":
            if os.path.exists(hash_file):
                with open(hash_file, "r") as f:
                    hash = f.read().strip()
                set_github_output(f"hash_{filter.name}", hash)
                set_github_env(f"hash_{filter.name}", hash)
                print(f"Filter {filter.name} - using cached hash '{hash}'", flush=True)
                write_to_step_summary(f"|{filter.name}|{hash}|yes|")
                continue
            else:
                update_filter = True
                print(
                    f"Filter {filter.name} - no cached hash found, calculating...", flush=True)


        start_time = time.time()
        hash = filter.calculate_hash(recursive_file_list("."))
        set_github_output(f"hash_{filter.name}", hash)
        set_github_env(f"hash_{filter.name}", hash)
        with open(hash_file, "w") as f:
            f.write(hash)
        end_time = time.time()
        duration = end_time - start_time
        print(
            f"Filter {filter.name} - hash: '{hash}' - took {duration:.3f} seconds", flush=True)
        write_to_step_summary(f"|{filter.name}|{hash}|no|")
