import os
import re

import utils.constants as constants
from utils.tools import get_real_path, resource_path, format_name


class Alias:
    def __init__(self):
        self.primary_to_aliases: dict[str, set[str]] = {}
        self.alias_to_primary: dict[str, str] = {}
        self.normalized_to_primary: dict[str, str] = {}
        self.pattern_to_primary: list[tuple[re.Pattern, str]] = []
        self._primary_cache: dict[str, str] = {}
        self._pattern_cache: dict[str, str | None] = {}

        real_path = get_real_path(resource_path(constants.alias_path))
        if os.path.exists(real_path):
            with open(real_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip() and not line.startswith("#") and "," in line:
                        parts = [p.strip() for p in line.split(",")]
                        primary = parts[0]
                        aliases = set(parts[1:])
                        aliases.add(format_name(primary))
                        self.primary_to_aliases[primary] = aliases
                        for alias in aliases:
                            self.alias_to_primary[alias] = primary
                            self.normalized_to_primary[format_name(alias)] = primary
                            if alias.startswith("re:"):
                                raw_pattern = alias[3:]
                                try:
                                    pattern = re.compile(raw_pattern)
                                    if (pattern, primary) not in self.pattern_to_primary:
                                        self.pattern_to_primary.append((pattern, primary))
                                except re.error:
                                    pass
                        self.alias_to_primary[primary] = primary
                        self.normalized_to_primary[format_name(primary)] = primary

    def get(self, name: str):
        """
        Get the alias by name
        """
        return self.primary_to_aliases.get(name, set())

    def get_primary(self, name: str):
        """
        Get the primary name by alias
        """
        if name in self._primary_cache:
            return self._primary_cache[name]

        primary_name = self.alias_to_primary.get(name, None)
        if primary_name is None:
            normalized_name = format_name(name)
            primary_name = self.alias_to_primary.get(normalized_name)
            if primary_name is None:
                primary_name = self.normalized_to_primary.get(normalized_name)
            if primary_name is None:
                primary_name = self.get_primary_by_pattern(name)
        if primary_name is None:
            alias_format_name = format_name(name)
            primary_name = self.alias_to_primary.get(alias_format_name) or self.normalized_to_primary.get(alias_format_name, name)

        self._primary_cache[name] = primary_name
        return primary_name

    def get_primary_by_pattern(self, name: str):
        """
        Get the primary name by pattern match
        """
        if name in self._pattern_cache:
            return self._pattern_cache[name]
        for pattern, primary in self.pattern_to_primary:
            if pattern.search(name):
                self._pattern_cache[name] = primary
                return primary
        self._pattern_cache[name] = None
        return None

    def set(self, name: str, aliases: set[str]):
        """
        Set the aliases by name
        """
        self._primary_cache.clear()
        self._pattern_cache.clear()
        if name in self.primary_to_aliases:
            for alias in self.primary_to_aliases[name]:
                self.alias_to_primary.pop(alias, None)
                self.normalized_to_primary.pop(format_name(alias), None)
        self.primary_to_aliases[name] = set(aliases)
        for alias in aliases:
            self.alias_to_primary[alias] = name
            self.normalized_to_primary[format_name(alias)] = name
            if alias.startswith("re:"):
                raw_pattern = alias[3:]
                try:
                    pattern = re.compile(raw_pattern)
                    if (pattern, name) not in self.pattern_to_primary:
                        self.pattern_to_primary.append((pattern, name))
                except re.error:
                    pass
        self.alias_to_primary[name] = name
        self.normalized_to_primary[format_name(name)] = name
