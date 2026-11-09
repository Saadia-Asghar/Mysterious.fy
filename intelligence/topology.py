"""M7: device dependency topology. An edge `child depends_on parent` means the child
needs the parent to be reachable (e.g. CAM-001 depends_on SWITCH-A)."""
from collections.abc import Iterable


class TopologyCycle(ValueError):
    pass


class Topology:
    def __init__(self, edges: Iterable[tuple[str, str]] = ()) -> None:
        self._parents: dict[str, set[str]] = {}
        for child, parent in edges:
            self.add(child, parent)

    def add(self, child: str, parent: str) -> None:
        if child == parent or child in self.ancestors(parent):
            raise TopologyCycle(f"{child} -> {parent} would create a cycle")
        self._parents.setdefault(child, set()).add(parent)

    def parents(self, device: str) -> set[str]:
        return set(self._parents.get(device, ()))

    def ancestors(self, device: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self._parents.get(device, ()))
        while stack:
            node = stack.pop()
            if node not in seen:
                seen.add(node)
                stack.extend(self._parents.get(node, ()))
        return seen

    def is_upstream_of(self, upstream: str, device: str) -> bool:
        return upstream in self.ancestors(device)

    def related(self, a: str, b: str) -> bool:
        """Directly related: same device, one upstream of the other, or siblings on a shared
        immediate parent. Sharing only a distant ancestor (e.g. the core switch) is NOT enough,
        so cameras on different access switches stay separate."""
        if a == b or self.is_upstream_of(a, b) or self.is_upstream_of(b, a):
            return True
        return bool(self.parents(a) & self.parents(b))

    def covers(self, candidate: str, device: str) -> bool:
        return candidate == device or self.is_upstream_of(candidate, device)
