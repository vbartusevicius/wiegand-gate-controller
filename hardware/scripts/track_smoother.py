"""DRC-safe octilinear (0/45/90 deg) post-route track smoother (`eda` container)."""

from __future__ import annotations

import itertools
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pcbnew
from shapely.geometry import LineString, Point, Polygon

SNAP_MM = 0.015  # 15 um endpoint snapping tolerance for chain extraction
CLEARANCE_MARGIN_MM = 0.015  # 15 um conservative safety margin over KiCad DRC
MAX_WINDOW = 8  # greedy lookahead window along degree-2 chains
MAX_TUNED_REDUCTION_MM = 1.0  # preserve intentional meanders on length-matched/diff nets
SELF_OVERLAP_GAP_MM = 0.04  # minimum gap to non-adjacent same-net segments/pads


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.parent.setdefault(x, x)
        r = x
        while self.parent[r] != r:
            r = self.parent[r]
        while self.parent[x] != r:
            nxt = self.parent[x]
            self.parent[x] = r
            x = nxt
        return r

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _pt_seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orient2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _segs_intersect(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float
) -> bool:
    if max(ax, bx) < min(cx, dx) - 1e-9 or max(cx, dx) < min(ax, bx) - 1e-9:
        return False
    if max(ay, by) < min(cy, dy) - 1e-9 or max(cy, dy) < min(ay, by) - 1e-9:
        return False
    o1 = _orient2d(ax, ay, bx, by, cx, cy)
    o2 = _orient2d(ax, ay, bx, by, dx, dy)
    o3 = _orient2d(cx, cy, dx, dy, ax, ay)
    o4 = _orient2d(cx, cy, dx, dy, bx, by)
    if (o1 > 1e-12 and o2 < -1e-12 or o1 < -1e-12 and o2 > 1e-12) and (
        o3 > 1e-12 and o4 < -1e-12 or o3 < -1e-12 and o4 > 1e-12
    ):
        return True
    return (
        _pt_seg_dist(cx, cy, ax, ay, bx, by) < 1e-9
        or _pt_seg_dist(dx, dy, ax, ay, bx, by) < 1e-9
        or _pt_seg_dist(ax, ay, cx, cy, dx, dy) < 1e-9
        or _pt_seg_dist(bx, by, cx, cy, dx, dy) < 1e-9
    )


def _seg_seg_dist(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float
) -> float:
    if _segs_intersect(ax, ay, bx, by, cx, cy, dx, dy):
        return 0.0
    return min(
        _pt_seg_dist(ax, ay, cx, cy, dx, dy),
        _pt_seg_dist(bx, by, cx, cy, dx, dy),
        _pt_seg_dist(cx, cy, ax, ay, bx, by),
        _pt_seg_dist(dx, dy, ax, ay, bx, by),
    )


def _poly_from_polyset(ps: pcbnew.SHAPE_POLY_SET, idx: int) -> Polygon:
    ext = ps.Outline(idx)
    shell = [(pcbnew.ToMM(ext.CPoint(k).x), pcbnew.ToMM(ext.CPoint(k).y)) for k in range(ext.PointCount())]
    holes = []
    for h in range(ps.HoleCount(idx)):
        hr = ps.Hole(idx, h)
        holes.append([(pcbnew.ToMM(hr.CPoint(k).x), pcbnew.ToMM(hr.CPoint(k).y)) for k in range(hr.PointCount())])
    return Polygon(shell, holes)


def _item_poly_mm(item: pcbnew.BOARD_ITEM, layer: int) -> Polygon | None:
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
    polys = [_poly_from_polyset(ps, i) for i in range(ps.OutlineCount()) if ps.Outline(i).PointCount() >= 3]
    if not polys:
        return None
    out = polys[0]
    for p in polys[1:]:
        out = out.union(p)
    return out


def _is_octilinear(ax: float, ay: float, bx: float, by: float, tol: float = 0.002) -> bool:
    adx, ady = abs(bx - ax), abs(by - ay)
    return adx <= tol or ady <= tol or abs(adx - ady) <= tol


def _octilinear_candidates(
    a: tuple[float, float], b: tuple[float, float]
) -> list[list[tuple[float, float]]]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    adx, ady = abs(dx), abs(dy)
    if math.hypot(dx, dy) < 1e-4:
        return []
    if _is_octilinear(ax, ay, bx, by):
        return [[a, b]]
    diag = min(adx, ady)
    sx = 1.0 if dx >= 0 else -1.0
    sy = 1.0 if dy >= 0 else -1.0
    m1 = (ax + sx * diag, ay + sy * diag)
    m2 = (bx - sx * diag, by - sy * diag)
    return [[a, m1, b], [a, m2, b]]


def _polyline_len(pts: list[tuple[float, float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(pts))


def _load_net_clearances(board: pcbnew.BOARD, pro_path: Path | None) -> tuple[dict[int, float], float, float]:
    ds = board.GetDesignSettings()
    base_clr = max(0.2, pcbnew.ToMM(getattr(ds, "m_MinClearance", pcbnew.FromMM(0.2))))
    edge_clr = max(0.25, pcbnew.ToMM(ds.m_CopperEdgeClearance))
    name_clr: dict[str, float] = {}
    if pro_path is not None and pro_path.exists():
        pro = json.loads(pro_path.read_text())
        ns = pro.get("net_settings", {})
        cls_clr = {c["name"]: float(c.get("clearance", base_clr)) for c in ns.get("classes", [])}
        base_clr = max(base_clr, cls_clr.get("Default", base_clr))
        for pat in ns.get("netclass_patterns", []):
            name_clr[pat["pattern"]] = max(base_clr, cls_clr.get(pat["netclass"], base_clr))

    by_code: dict[int, float] = {}
    for net in board.GetNetsByNetcode().values():
        nc = net.GetNetCode()
        if nc > 0:
            by_code[nc] = name_clr.get(net.GetNetname(), base_clr)
    return by_code, base_clr, edge_clr


def _detect_tuned_nets(board: pcbnew.BOARD, extra_tuned: set[str] | None = None) -> set[int]:
    tuned_names = set(extra_tuned or ())
    names = {net.GetNetname(): net.GetNetCode() for net in board.GetNetsByNetcode().values() if net.GetNetCode() > 0}
    # Auto-detect differential pairs (e.g. *_P/*_N or *+/*-)
    for nm in names:
        if nm.endswith("_P") and (nm[:-2] + "_N") in names:
            tuned_names.update((nm, nm[:-2] + "_N"))
        elif nm.endswith("+") and (nm[:-1] + "-") in names:
            tuned_names.update((nm, nm[:-1] + "-"))
    return {names[n] for n in tuned_names if n in names}


@dataclass
class _PadObs:
    net_code: int
    is_circle: bool
    cx: float
    cy: float
    radius: float
    poly: Polygon | None
    bbox: tuple[float, float, float, float]


@dataclass
class _ViaObs:
    net_code: int
    cx: float
    cy: float
    radius: float
    drill_r: float


@dataclass
class _TrackObs:
    net_code: int
    ax: float
    ay: float
    bx: float
    by: float
    half_w: float
    bbox: tuple[float, float, float, float]


class _LayerChecker:
    """Fast exact geometric clearance checker for one copper layer."""

    def __init__(
        self,
        board: pcbnew.BOARD,
        layer: int,
        board_poly: Polygon,
        edge_clr: float,
        net_clr: dict[int, float],
        base_clr: float,
        keepouts: list[Polygon],
        unnetted_holes: list[_PadObs],
        pads: list[_PadObs],
        vias: list[_ViaObs],
        tracks_by_net: dict[int, list[_TrackObs]],
    ) -> None:
        self.layer = layer
        self.board_poly = board_poly
        self.edge_clr = edge_clr
        self.net_clr = net_clr
        self.base_clr = base_clr
        self.keepouts = keepouts
        self.keepout_bboxes = [p.bounds for p in keepouts]
        self.unnetted_holes = unnetted_holes
        self.pads = pads
        self.vias = vias
        self.tracks_by_net = tracks_by_net
        self._inset_cache: dict[int, Polygon] = {}

    def _board_inset(self, half_w: float) -> Polygon:
        key = round((self.edge_clr + half_w + CLEARANCE_MARGIN_MM) * 1000)
        if key not in self._inset_cache:
            self._inset_cache[key] = self.board_poly.buffer(-(key / 1000.0))
        return self._inset_cache[key]

    def _req_clr(self, net_a: int, net_b: int) -> float:
        return max(self.net_clr.get(net_a, self.base_clr), self.net_clr.get(net_b, self.base_clr)) + CLEARANCE_MARGIN_MM

    def segment_clear(
        self,
        net_code: int,
        a: tuple[float, float],
        b: tuple[float, float],
        width: float,
        same_net_other_segs: list[tuple[tuple[float, float], tuple[float, float], float]],
        endpoint_coords: tuple[tuple[float, float], tuple[float, float]],
    ) -> bool:
        ax, ay = a
        bx, by = b
        half_w = width * 0.5
        seg_line = LineString([a, b])

        # 1. Board outline & internal cutouts
        inset = self._board_inset(half_w)
        if inset.is_empty or not inset.covers(seg_line):
            return False

        x0, x1 = min(ax, bx), max(ax, bx)
        y0, y1 = min(ay, by), max(ay, by)
        my_clr = self.net_clr.get(net_code, self.base_clr)
        max_pad = half_w + max(my_clr, self.base_clr) + CLEARANCE_MARGIN_MM

        # 2. KiCad rule-area keepout zones (track-disallowed areas on this layer)
        for kp, (kx0, ky0, kx1, ky1) in zip(self.keepouts, self.keepout_bboxes):
            if x1 + half_w + CLEARANCE_MARGIN_MM < kx0 or kx1 < x0 - half_w - CLEARANCE_MARGIN_MM:
                continue
            if y1 + half_w + CLEARANCE_MARGIN_MM < ky0 or ky1 < y0 - half_w - CLEARANCE_MARGIN_MM:
                continue
            if seg_line.distance(kp) < half_w + CLEARANCE_MARGIN_MM:
                return False

        # 3. Unnetted mounting holes / NPTH cutouts (exact circle distance for round holes)
        hole_req = max(self.edge_clr, my_clr) + CLEARANCE_MARGIN_MM
        for h in self.unnetted_holes:
            hx0, hy0, hx1, hy1 = h.bbox
            if x1 + half_w + hole_req < hx0 or hx1 < x0 - half_w - hole_req:
                continue
            if y1 + half_w + hole_req < hy0 or hy1 < y0 - half_w - hole_req:
                continue
            if h.is_circle:
                d = _pt_seg_dist(h.cx, h.cy, ax, ay, bx, by) - h.radius - half_w
            else:
                assert h.poly is not None
                d = seg_line.distance(h.poly) - half_w
            if d < hole_req:
                return False

        # 4. Other-net pads (exact circle radius for PAD_SHAPE_CIRCLE, exact polygon for others)
        #    and non-local same-net pads (reject passing through an unrelated same-net pad)
        ep0, ep1 = endpoint_coords
        for p in self.pads:
            px0, py0, px1, py1 = p.bbox
            if p.net_code == net_code:
                # Allow touching only pads that own one of the shortcut's endpoints
                if (
                    math.hypot(p.cx - ep0[0], p.cy - ep0[1]) <= p.radius + 0.05
                    or math.hypot(p.cx - ep1[0], p.cy - ep1[1]) <= p.radius + 0.05
                ):
                    continue
                if p.poly is not None and (
                    p.poly.buffer(0.05).contains(Point(ep0)) or p.poly.buffer(0.05).contains(Point(ep1))
                ):
                    continue
                if x1 + half_w + SELF_OVERLAP_GAP_MM < px0 or px1 < x0 - half_w - SELF_OVERLAP_GAP_MM:
                    continue
                if y1 + half_w + SELF_OVERLAP_GAP_MM < py0 or py1 < y0 - half_w - SELF_OVERLAP_GAP_MM:
                    continue
                d_self = (
                    _pt_seg_dist(p.cx, p.cy, ax, ay, bx, by) - p.radius - half_w
                    if p.is_circle
                    else (seg_line.distance(p.poly) - half_w if p.poly is not None else 1e9)
                )
                if d_self < SELF_OVERLAP_GAP_MM:
                    return False
                continue

            req = self._req_clr(net_code, p.net_code)
            if x1 + half_w + req < px0 or px1 < x0 - half_w - req:
                continue
            if y1 + half_w + req < py0 or py1 < y0 - half_w - req:
                continue
            if p.is_circle:
                d = _pt_seg_dist(p.cx, p.cy, ax, ay, bx, by) - p.radius - half_w
            else:
                assert p.poly is not None
                d = seg_line.distance(p.poly) - half_w
            if d < req:
                return False

        # 5. Other-net vias (and non-local same-net vias)
        for v in self.vias:
            if v.net_code == net_code:
                if (
                    math.hypot(v.cx - ep0[0], v.cy - ep0[1]) <= SNAP_MM + 0.01
                    or math.hypot(v.cx - ep1[0], v.cy - ep1[1]) <= SNAP_MM + 0.01
                ):
                    continue
                if _pt_seg_dist(v.cx, v.cy, ax, ay, bx, by) - v.radius - half_w < SELF_OVERLAP_GAP_MM:
                    return False
                continue
            req = self._req_clr(net_code, v.net_code)
            if abs(v.cx - 0.5 * (x0 + x1)) > 0.5 * (x1 - x0) + v.radius + half_w + req:
                continue
            if abs(v.cy - 0.5 * (y0 + y1)) > 0.5 * (y1 - y0) + v.radius + half_w + req:
                continue
            d_copper = _pt_seg_dist(v.cx, v.cy, ax, ay, bx, by) - v.radius - half_w
            if d_copper < req:
                return False
            d_hole = _pt_seg_dist(v.cx, v.cy, ax, ay, bx, by) - v.drill_r - half_w
            if d_hole < max(req, 0.25 + CLEARANCE_MARGIN_MM):
                return False

        # 6. All other-net tracks on this layer
        for other_nc, tlist in self.tracks_by_net.items():
            if other_nc == net_code:
                continue
            req = self._req_clr(net_code, other_nc)
            pad_r = half_w + req
            for t in tlist:
                tx0, ty0, tx1, ty1 = t.bbox
                if x1 + pad_r < tx0 or tx1 < x0 - pad_r or y1 + pad_r < ty0 or ty1 < y0 - pad_r:
                    continue
                if _seg_seg_dist(ax, ay, bx, by, t.ax, t.ay, t.bx, t.by) - half_w - t.half_w < req:
                    return False

        # 7. Same-net self-crossing & non-local copper self-overlap check
        for (sa, sb, sw) in same_net_other_segs:
            shw = sw * 0.5
            # Check if this same-net segment is directly adjacent at endpoint a or b
            touches_a = math.hypot(sa[0] - ax, sa[1] - ay) <= SNAP_MM or math.hypot(sb[0] - ax, sb[1] - ay) <= SNAP_MM
            touches_b = math.hypot(sa[0] - bx, sa[1] - by) <= SNAP_MM or math.hypot(sb[0] - bx, sb[1] - by) <= SNAP_MM
            if touches_a or touches_b:
                # Reject acute fold-back (< 45 deg) that causes local copper self-overlap
                shared = a if touches_a else b
                other_cand = b if touches_a else a
                other_seg = sb if math.hypot(sa[0] - shared[0], sa[1] - shared[1]) <= SNAP_MM else sa
                v1x, v1y = other_cand[0] - shared[0], other_cand[1] - shared[1]
                v2x, v2y = other_seg[0] - shared[0], other_seg[1] - shared[1]
                l1, l2 = math.hypot(v1x, v1y), math.hypot(v2x, v2y)
                if l1 > 1e-6 and l2 > 1e-6:
                    cos_ang = (v1x * v2x + v1y * v2y) / (l1 * l2)
                    if cos_ang > 0.75:  # < ~41 deg fold-back onto adjacent same-net trace
                        return False
                continue
            if _seg_seg_dist(ax, ay, bx, by, sa[0], sa[1], sb[0], sb[1]) - half_w - shw < SELF_OVERLAP_GAP_MM:
                return False

        _ = max_pad
        return True


def _extract_chains(
    segs: list[tuple[tuple[float, float], tuple[float, float], float]],
    pinned_pts: list[tuple[float, float]],
    same_net_pads: list[_PadObs],
    snap_mm: float = SNAP_MM,
) -> list[tuple[list[tuple[float, float]], list[float], bool]]:
    """Snap endpoints within snap_mm and extract maximal degree-2 chains between pinned vertices."""
    if not segs:
        return []

    # Build canonical point list: pinned pad/via centers first so their exact coordinates win cluster representatives
    pts: list[tuple[float, float]] = list(pinned_pts)
    n_pin_raw = len(pts)
    seg_raw_idx: list[tuple[int, int, float]] = []
    for a, b, w in segs:
        ia = len(pts)
        pts.append(a)
        ib = len(pts)
        pts.append(b)
        seg_raw_idx.append((ia, ib, w))

    uf = _UnionFind()
    cell = max(snap_mm, 1e-3)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, (x, y) in enumerate(pts):
        uf.find(idx)
        gx, gy = math.floor(x / cell), math.floor(y / cell)
        for nx in (gx - 1, gx, gx + 1):
            for ny in (gy - 1, gy, gy + 1):
                for j in grid.get((nx, ny), ()):
                    if math.hypot(x - pts[j][0], y - pts[j][1]) <= snap_mm:
                        # Always union toward lower index so exact pad/via centers stay roots
                        uf.union(min(idx, j), max(idx, j))
        grid[(gx, gy)].append(idx)

    # Canonical coordinates per root (exact pad/via center if any pinned point is in cluster)
    root_coord: dict[int, tuple[float, float]] = {}
    pinned_roots: set[int] = set()
    for idx, pt in enumerate(pts):
        r = uf.find(idx)
        if idx < n_pin_raw:
            pinned_roots.add(r)
            root_coord.setdefault(r, pt)
        else:
            root_coord.setdefault(r, pt)

    # Build undirected edge list & adjacency
    edges: list[tuple[int, int, float]] = []
    adj: dict[int, list[int]] = defaultdict(list)
    for ia, ib, w in seg_raw_idx:
        u, v = uf.find(ia), uf.find(ib)
        if u == v:
            continue
        eid = len(edges)
        edges.append((u, v, w))
        adj[u].append(eid)
        adj[v].append(eid)

    for v, elist in adj.items():
        if len(elist) != 2:
            pinned_roots.add(v)
            continue
        vx, vy = root_coord[v]
        # Pin any degree-2 vertex landing anywhere inside an oblong/rectangular same-net pad (e.g. WAGO 1.6x3.9mm)
        for p in same_net_pads:
            px0, py0, px1, py1 = p.bbox
            if vx < px0 - snap_mm or vx > px1 + snap_mm or vy < py0 - snap_mm or vy > py1 + snap_mm:
                continue
            if p.is_circle:
                if math.hypot(vx - p.cx, vy - p.cy) <= p.radius + snap_mm:
                    pinned_roots.add(v)
                    break
            elif p.poly is not None and p.poly.buffer(snap_mm).contains(Point(vx, vy)):
                pinned_roots.add(v)
                break

    visited: set[int] = set()
    chains: list[tuple[list[tuple[float, float]], list[float], bool]] = []

    def walk_from(start_v: int, first_eid: int) -> None:
        verts = [start_v]
        widths = []
        cur_v = start_v
        cur_e = first_eid
        while True:
            visited.add(cur_e)
            u, v, w = edges[cur_e]
            nxt_v = v if u == cur_v else u
            verts.append(nxt_v)
            widths.append(w)
            cur_v = nxt_v
            if cur_v in pinned_roots:
                break
            nxt_edges = [e for e in adj[cur_v] if e not in visited]
            if not nxt_edges:
                break
            cur_e = nxt_edges[0]
        chains.append(([root_coord[k] for k in verts], widths, False))

    for v in sorted(pinned_roots):
        for eid in adj.get(v, ()):
            if eid not in visited:
                walk_from(v, eid)

    # Pure closed cycles (rare after track_pruner, preserved intact)
    for eid in range(len(edges)):
        if eid not in visited:
            u, _, _ = edges[eid]
            walk_from(u, eid)
            pts_c, ws_c, _ = chains[-1]
            chains[-1] = (pts_c, ws_c, True)

    return chains


def _smooth_chain(
    pts: list[tuple[float, float]],
    widths: list[float],
    net_code: int,
    checker: _LayerChecker,
    other_chains_segs: list[tuple[tuple[float, float], tuple[float, float], float]],
    *,
    is_tuned: bool,
    min_required_width: float,
    courtyard_polys: list[Polygon],
) -> tuple[list[tuple[float, float]], list[float], int]:
    """Greedy octilinear shortcutting along one degree-2 chain."""
    if len(pts) < 3:
        return pts, widths, 0

    chain_min_w = min(widths)
    cur_pts = list(pts)
    cur_ws = list(widths)
    shortcuts = 0

    for _pass in range(4):
        improved = False
        i = 0
        while i < len(cur_pts) - 2:
            max_j = min(len(cur_pts) - 1, i + MAX_WINDOW)
            accepted = False
            for j in range(max_j, i + 1, -1):
                orig_sub = cur_pts[i : j + 1]
                orig_len = _polyline_len(orig_sub)
                orig_segs = j - i
                sub_ws = cur_ws[i:j]
                sub_max_w = max(sub_ws)
                # Preserve wider power width outside fine-pitch courtyards when possible; fall back to min(chain_widths)
                width_trials = [sub_max_w] if abs(sub_max_w - chain_min_w) < 1e-6 else [sub_max_w, chain_min_w]

                # Same-net segments outside sub-chain [i..j] on this layer
                same_other = list(other_chains_segs)
                for k in range(len(cur_pts) - 1):
                    if i <= k < j:
                        continue
                    same_other.append((cur_pts[k], cur_pts[k + 1], cur_ws[k]))

                cands = _octilinear_candidates(cur_pts[i], cur_pts[j])
                # Prefer strictly shorter candidates, then fewer segments
                cands.sort(key=lambda c: (_polyline_len(c), len(c)))

                for cand in cands:
                    cand_len = _polyline_len(cand)
                    cand_segs = len(cand) - 1
                    reduction = orig_len - cand_len
                    is_better = (reduction > 0.005) or (cand_segs < orig_segs and reduction >= -0.005)
                    if not is_better:
                        continue
                    if is_tuned and reduction > MAX_TUNED_REDUCTION_MM:
                        continue

                    for w_try in width_trials:
                        # Never narrow a power segment below DRC minimum outside fine-pitch courtyards
                        if w_try < min_required_width - 1e-6 and not all(
                            any(cp.intersects(LineString([ca, cb])) for cp in courtyard_polys)
                            for ca, cb in itertools.pairwise(cand)
                        ):
                            continue
                        ok = True
                        for s_idx, (ca, cb) in enumerate(itertools.pairwise(cand)):
                            # Also check sibling segment of 2-segment dogleg isn't zero-length
                            if math.hypot(cb[0] - ca[0], cb[1] - ca[1]) < 0.002:
                                ok = False
                                break
                            # Include the sibling dogleg segment in same-net list if needed (shares endpoint m -> valid 135 deg)
                            local_other = same_other
                            if not checker.segment_clear(
                                net_code,
                                ca,
                                cb,
                                w_try,
                                local_other,
                                (cur_pts[i], cur_pts[j]),
                            ):
                                ok = False
                                break
                        if ok:
                            cur_pts = cur_pts[: i + 1] + cand[1:-1] + cur_pts[j:]
                            cur_ws = cur_ws[:i] + [w_try] * cand_segs + cur_ws[j:]
                            shortcuts += 1
                            improved = True
                            accepted = True
                            break
                    if accepted:
                        break
                if accepted:
                    break
            i += 1
        if not improved:
            break

    return cur_pts, cur_ws, shortcuts


def smooth_board_tracks(
    board: pcbnew.BOARD,
    *,
    pro_path: Path | None = None,
    plan: dict | None = None,
    tuned_nets: set[str] | None = None,
) -> dict[str, float | int]:
    """Run DRC-safe octilinear track smoothing across all non-plane copper nets & layers."""
    cu_layers = list(board.GetEnabledLayers().CuStack())
    net_clr, base_clr, edge_clr = _load_net_clearances(board, pro_path)
    tuned_codes = _detect_tuned_nets(board, tuned_nets)

    # Skip plane/pour nets (e.g. GND on In1.Cu)
    plane_net_codes = {
        z.GetNetCode() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetCode() > 0
    }

    # Board outline polygon (with any internal cutouts)
    out_ps = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(out_ps, False)
    board_polys = [_poly_from_polyset(out_ps, i) for i in range(out_ps.OutlineCount()) if out_ps.Outline(i).PointCount() >= 3]
    board_poly = board_polys[0]
    for bp in board_polys[1:]:
        board_poly = board_poly.union(bp)

    # Fine-pitch neck-down courtyards & MAIN-Power minimum track width outside courtyards
    frame = (plan or {}).get("frame", {})
    power_net_names = set(frame.get("power_nets", []))
    fine_pitch_refs = set(frame.get("fine_pitch_power_pads", []))
    courtyard_polys: list[Polygon] = []
    for ref in fine_pitch_refs:
        fp = board.FindFootprintByReference(ref)
        if fp is None:
            continue
        fp.BuildCourtyardCaches()
        c_ps = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
        for i in range(c_ps.OutlineCount()):
            if c_ps.Outline(i).PointCount() >= 3:
                courtyard_polys.append(_poly_from_polyset(c_ps, i))

    # Pre-extract per-layer obstacles (pads, unnetted holes, vias, rule-area keepouts)
    keepouts_by_layer: dict[int, list[Polygon]] = defaultdict(list)
    for z in board.Zones():
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
            for lyr in cu_layers:
                if z.IsOnLayer(lyr):
                    ol = z.Outline()
                    for i in range(ol.OutlineCount()):
                        if ol.Outline(i).PointCount() >= 3:
                            keepouts_by_layer[lyr].append(_poly_from_polyset(ol, i))

    pads_by_layer: dict[int, list[_PadObs]] = defaultdict(list)
    unnetted_holes: list[_PadObs] = []
    pad_centers_by_net_layer: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for fp in board.Footprints():
        for pad in fp.Pads():
            nc = pad.GetNetCode()
            p = pad.GetPosition()
            cx, cy = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
            drill_x = pcbnew.ToMM(pad.GetDrillSize().x)
            drill_y = pcbnew.ToMM(pad.GetDrillSize().y)
            is_circ = pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE
            if nc == 0 and drill_x > 0:
                r = 0.5 * max(drill_x, drill_y)
                poly = Point(cx, cy).buffer(r) if is_circ else _item_poly_mm(pad, pcbnew.F_Cu)
                bbox = (cx - r, cy - r, cx + r, cy + r) if is_circ else (poly.bounds if poly else (cx - r, cy - r, cx + r, cy + r))
                unnetted_holes.append(_PadObs(0, is_circ, cx, cy, r, poly, bbox))
                continue
            for lyr in cu_layers:
                if not pad.IsOnLayer(lyr):
                    continue
                if nc > 0:
                    pad_centers_by_net_layer[(nc, lyr)].append((cx, cy))
                if is_circ:
                    r = 0.5 * pcbnew.ToMM(pad.GetSize().x)
                    pads_by_layer[lyr].append(_PadObs(nc, True, cx, cy, r, None, (cx - r, cy - r, cx + r, cy + r)))
                else:
                    poly = _item_poly_mm(pad, lyr)
                    if poly is None:
                        continue
                    r = 0.5 * max(pcbnew.ToMM(pad.GetSize().x), pcbnew.ToMM(pad.GetSize().y))
                    pads_by_layer[lyr].append(_PadObs(nc, False, cx, cy, r, poly, poly.bounds))

    vias_by_layer: dict[int, list[_ViaObs]] = defaultdict(list)
    via_centers_by_net_layer: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for tr in board.GetTracks():
        if tr.GetClass() != "PCB_VIA":
            continue
        nc = tr.GetNetCode()
        p = tr.GetPosition()
        cx, cy = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
        r = 0.5 * pcbnew.ToMM(tr.GetWidth(pcbnew.F_Cu))
        dr = 0.5 * pcbnew.ToMM(tr.GetDrillValue())
        obs = _ViaObs(nc, cx, cy, r, dr)
        for lyr in cu_layers:
            if tr.IsOnLayer(lyr):
                vias_by_layer[lyr].append(obs)
                if nc > 0:
                    via_centers_by_net_layer[(nc, lyr)].append((cx, cy))

    # Index all existing tracks by layer -> net_code
    layer_net_tracks: dict[int, dict[int, list[pcbnew.PCB_TRACK]]] = {lyr: defaultdict(list) for lyr in cu_layers}
    layer_obs_tracks: dict[int, dict[int, list[_TrackObs]]] = {lyr: defaultdict(list) for lyr in cu_layers}
    len_before = 0.0
    segs_before = 0

    for tr in list(board.GetTracks()):
        if tr.GetClass() == "PCB_VIA" or tr.GetNetCode() <= 0:
            continue
        lyr = tr.GetLayer()
        if lyr not in layer_net_tracks:
            continue
        nc = tr.GetNetCode()
        s, e = tr.GetStart(), tr.GetEnd()
        ax, ay, bx, by = pcbnew.ToMM(s.x), pcbnew.ToMM(s.y), pcbnew.ToMM(e.x), pcbnew.ToMM(e.y)
        w = pcbnew.ToMM(tr.GetWidth())
        len_before += math.hypot(bx - ax, by - ay)
        segs_before += 1
        layer_obs_tracks[lyr][nc].append(
            _TrackObs(nc, ax, ay, bx, by, w * 0.5, (min(ax, bx) - w * 0.5, min(ay, by) - w * 0.5, max(ax, bx) + w * 0.5, max(ay, by) + w * 0.5))
        )
        if not tr.IsLocked() and tr.GetClass() == "PCB_TRACK":
            layer_net_tracks[lyr][nc].append(tr)

    total_shortcuts = 0
    nets_smoothed = 0

    for lyr in cu_layers:
        checker = _LayerChecker(
            board=board,
            layer=lyr,
            board_poly=board_poly,
            edge_clr=edge_clr,
            net_clr=net_clr,
            base_clr=base_clr,
            keepouts=keepouts_by_layer[lyr],
            unnetted_holes=unnetted_holes,
            pads=pads_by_layer[lyr],
            vias=vias_by_layer[lyr],
            tracks_by_net=layer_obs_tracks[lyr],
        )

        for nc in sorted(layer_net_tracks[lyr]):
            if nc in plane_net_codes:
                continue
            tr_objs = layer_net_tracks[lyr][nc]
            if len(tr_objs) < 2:
                continue
            net_info = board.FindNet(nc)
            net_name = net_info.GetNetname()
            min_req_w = 0.22 if net_name in power_net_names else 0.12

            raw_segs = [
                (
                    (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)),
                    (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)),
                    pcbnew.ToMM(t.GetWidth()),
                )
                for t in tr_objs
            ]
            pinned = pad_centers_by_net_layer[(nc, lyr)] + via_centers_by_net_layer[(nc, lyr)]
            same_pads = [p for p in pads_by_layer[lyr] if p.net_code == nc]
            chains = _extract_chains(raw_segs, pinned, same_pads, SNAP_MM)
            if not chains:
                continue

            # Keep locked/arc tracks of this net as immutable same-net obstacles
            locked_same = [
                ((t.ax, t.ay), (t.bx, t.by), t.half_w * 2.0)
                for t in layer_obs_tracks[lyr][nc]
            ]
            # Rebuild exact locked-only set by subtracting raw_segs count
            locked_same = [
                (
                    (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)),
                    (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)),
                    pcbnew.ToMM(t.GetWidth()),
                )
                for t in board.GetTracks()
                if t.GetClass() != "PCB_VIA"
                and t.GetLayer() == lyr
                and t.GetNetCode() == nc
                and (t.IsLocked() or t.GetClass() != "PCB_TRACK")
            ]

            new_chains = [list(c[0]) for c in chains]
            new_widths = [list(c[1]) for c in chains]
            net_shortcuts = 0

            for idx, (_, _, is_cycle) in enumerate(chains):
                if is_cycle or len(new_chains[idx]) < 3:
                    continue
                other_segs = list(locked_same)
                for o_idx, (oc, ow) in enumerate(zip(new_chains, new_widths)):
                    if o_idx == idx:
                        continue
                    for (oa, ob), w_o in zip(itertools.pairwise(oc), ow):
                        other_segs.append((oa, ob, w_o))

                s_pts, s_ws, sc = _smooth_chain(
                    new_chains[idx],
                    new_widths[idx],
                    nc,
                    checker,
                    other_segs,
                    is_tuned=(nc in tuned_codes),
                    min_required_width=min_req_w,
                    courtyard_polys=courtyard_polys,
                )
                if sc > 0:
                    new_chains[idx] = s_pts
                    new_widths[idx] = s_ws
                    net_shortcuts += sc

            if net_shortcuts == 0:
                continue

            # Final same-net self-crossing guard across all chains of this net on this layer
            final_segs: list[tuple[tuple[float, float], tuple[float, float], float]] = list(locked_same)
            for c_pts, c_ws in zip(new_chains, new_widths):
                for (ca, cb), cw in zip(itertools.pairwise(c_pts), c_ws):
                    final_segs.append((ca, cb, cw))

            has_self_cross = False
            for i in range(len(final_segs)):
                a0, a1, wa = final_segs[i]
                for j in range(i + 1, len(final_segs)):
                    b0, b1, wb = final_segs[j]
                    # Skip segments sharing an endpoint
                    if (
                        math.hypot(a0[0] - b0[0], a0[1] - b0[1]) <= SNAP_MM
                        or math.hypot(a0[0] - b1[0], a0[1] - b1[1]) <= SNAP_MM
                        or math.hypot(a1[0] - b0[0], a1[1] - b0[1]) <= SNAP_MM
                        or math.hypot(a1[0] - b1[0], a1[1] - b1[1]) <= SNAP_MM
                    ):
                        continue
                    if _seg_seg_dist(a0[0], a0[1], a1[0], a1[1], b0[0], b0[1], b1[0], b1[1]) - 0.5 * (wa + wb) < SELF_OVERLAP_GAP_MM:
                        has_self_cross = True
                        break
                if has_self_cross:
                    break
            if has_self_cross:
                continue

            # Commit smoothed tracks for (nc, lyr) and refresh live obstacle index
            for old_tr in tr_objs:
                board.RemoveNative(old_tr)

            updated_obs = [
                _TrackObs(nc, a[0], a[1], b[0], b[1], w * 0.5, (min(a[0], b[0]) - w * 0.5, min(a[1], b[1]) - w * 0.5, max(a[0], b[0]) + w * 0.5, max(a[1], b[1]) + w * 0.5))
                for a, b, w in locked_same
            ]
            for c_pts, c_ws in zip(new_chains, new_widths):
                for (ca, cb), cw in zip(itertools.pairwise(c_pts), c_ws):
                    nt = pcbnew.PCB_TRACK(board)
                    nt.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(ca[0]), pcbnew.FromMM(ca[1])))
                    nt.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(cb[0]), pcbnew.FromMM(cb[1])))
                    nt.SetWidth(pcbnew.FromMM(cw))
                    nt.SetLayer(lyr)
                    board.Add(nt)
                    nt.SetNet(net_info)
                    updated_obs.append(
                        _TrackObs(nc, ca[0], ca[1], cb[0], cb[1], cw * 0.5, (min(ca[0], cb[0]) - cw * 0.5, min(ca[1], cb[1]) - cw * 0.5, max(ca[0], cb[0]) + cw * 0.5, max(ca[1], cb[1]) + cw * 0.5))
                    )
            layer_obs_tracks[lyr][nc] = updated_obs
            total_shortcuts += net_shortcuts
            nets_smoothed += 1

    len_after = 0.0
    segs_after = 0
    for tr in board.GetTracks():
        if tr.GetClass() != "PCB_VIA" and tr.GetNetCode() > 0:
            s, e = tr.GetStart(), tr.GetEnd()
            len_after += math.hypot(pcbnew.ToMM(e.x - s.x), pcbnew.ToMM(e.y - s.y))
            segs_after += 1

    return {
        "segs_before": segs_before,
        "segs_after": segs_after,
        "len_before_mm": round(len_before, 2),
        "len_after_mm": round(len_after, 2),
        "shortcuts": total_shortcuts,
        "nets_smoothed": nets_smoothed,
    }
