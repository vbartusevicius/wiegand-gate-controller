"""Post-route planar track splitter and cycle/stub Steiner-tree pruner (`eda` container)."""

from __future__ import annotations

import itertools
import math
from collections import defaultdict, deque

import pcbnew
from shapely.geometry import Point, Polygon

TOL_NM = 1000  # 1.0 um endpoint/junction clustering tolerance


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            nxt = self.parent[x]
            self.parent[x] = root
            x = nxt
        return root

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[rb] = ra
        return True


def poly_from_outline(polyset: pcbnew.SHAPE_POLY_SET, idx: int) -> Polygon:
    ext = polyset.Outline(idx)
    shell = [(pcbnew.ToMM(ext.CPoint(k).x), pcbnew.ToMM(ext.CPoint(k).y)) for k in range(ext.PointCount())]
    holes = []
    for h in range(polyset.HoleCount(idx)):
        hr = polyset.Hole(idx, h)
        holes.append([(pcbnew.ToMM(hr.CPoint(k).x), pcbnew.ToMM(hr.CPoint(k).y)) for k in range(hr.PointCount())])
    return Polygon(shell, holes)


def item_polys_mm(item: pcbnew.BOARD_ITEM, layer: int) -> list[Polygon]:
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
    return [poly_from_outline(ps, i) for i in range(ps.OutlineCount()) if ps.Outline(i).PointCount() >= 3]


def param_on_seg(px: float, py: float, ax: float, ay: float, bx: float, by: float, tol: float = TOL_NM) -> float | None:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 <= 0:
        return None
    t = ((px - ax) * dx + (py - ay) * dy) / len2
    if t <= 1e-6 or t >= 1.0 - 1e-6:
        return None
    cx, cy = ax + t * dx, ay + t * dy
    if math.hypot(px - cx, py - cy) <= tol:
        return t
    return None


def seg_crossing_params(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float
) -> tuple[float, float] | None:
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-3:
        return None
    qpx, qpy = cx - ax, cy - ay
    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom
    if 1e-6 < t < 1.0 - 1e-6 and 1e-6 < u < 1.0 - 1e-6:
        return t, u
    return None


def split_planar_segments(
    segs: list[tuple[int, int, int, int, int]],
    junction_pts: list[tuple[int, int]],
) -> list[tuple[int, int, int, int, int]]:
    n = len(segs)
    if n == 0:
        return []
    splits: list[list[float]] = [[0.0, 1.0] for _ in range(n)]
    bboxes = [(min(a, c) - TOL_NM, min(b, d) - TOL_NM, max(a, c) + TOL_NM, max(b, d) + TOL_NM) for a, b, c, d, _ in segs]

    for i in range(n):
        ax, ay, bx, by, _ = segs[i]
        ix0, iy0, ix1, iy1 = bboxes[i]
        for px, py in junction_pts:
            if ix0 <= px <= ix1 and iy0 <= py <= iy1:
                t = param_on_seg(px, py, ax, ay, bx, by)
                if t is not None:
                    splits[i].append(t)
        for j in range(i + 1, n):
            jx0, jy0, jx1, jy1 = bboxes[j]
            if ix1 < jx0 or jx1 < ix0 or iy1 < jy0 or jy1 < iy0:
                continue
            cx, cy, dx, dy, _ = segs[j]
            cross = seg_crossing_params(ax, ay, bx, by, cx, cy, dx, dy)
            if cross is not None:
                splits[i].append(cross[0])
                splits[j].append(cross[1])
            for px, py in ((cx, cy), (dx, dy)):
                t = param_on_seg(px, py, ax, ay, bx, by)
                if t is not None:
                    splits[i].append(t)
            for px, py in ((ax, ay), (bx, by)):
                u = param_on_seg(px, py, cx, cy, dx, dy)
                if u is not None:
                    splits[j].append(u)

    atomic: list[tuple[int, int, int, int, int]] = []
    for i, (ax, ay, bx, by, w) in enumerate(segs):
        ts = sorted({round(t, 7) for t in splits[i]})
        for t0, t1 in itertools.pairwise(ts):
            x0 = round(ax + t0 * (bx - ax))
            y0 = round(ay + t0 * (by - ay))
            x1 = round(ax + t1 * (bx - ax))
            y1 = round(ay + t1 * (by - ay))
            if math.hypot(x1 - x0, y1 - y0) >= 200:
                atomic.append((x0, y0, x1, y1, w))
    return atomic


def cluster_points(pts: list[tuple[int, int]], tol: int = TOL_NM) -> tuple[dict[tuple[int, int], int], dict[int, tuple[int, int]]]:
    uniq = sorted(set(pts))
    uf = UnionFind()
    cell_size = max(1, tol)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, (x, y) in enumerate(uniq):
        gx, gy = x // cell_size, y // cell_size
        for nx in (gx - 1, gx, gx + 1):
            for ny in (gy - 1, gy, gy + 1):
                for j in grid.get((nx, ny), ()):
                    ox, oy = uniq[j]
                    if math.hypot(x - ox, y - oy) <= tol:
                        uf.union(idx, j)
        grid[(gx, gy)].append(idx)
    pt_to_cid = {}
    cid_coords: dict[int, tuple[int, int]] = {}
    for idx, pt in enumerate(uniq):
        root = uf.find(idx)
        pt_to_cid[pt] = root
        cid_coords.setdefault(root, uniq[root])
    return pt_to_cid, cid_coords


def merge_collinear(
    edges: list[tuple[int, int, int]],
    coords: dict[int, tuple[int, int]],
    pinned_cids: set[int],
) -> list[tuple[int, int, int]]:
    adj: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for u, v, w in edges:
        adj[u].append((v, w))
        adj[v].append((u, w))

    changed = True
    while changed:
        changed = False
        for mid in list(adj):
            if mid in pinned_cids or len(adj[mid]) != 2:
                continue
            (a, w1), (b, w2) = adj[mid]
            if a == b or w1 != w2:
                continue
            ax, ay = coords[a]
            mx, my = coords[mid]
            bx, by = coords[b]
            ux, uy = mx - ax, my - ay
            vx, vy = bx - mx, by - my
            if ux * vx + uy * vy <= 0:
                continue
            ab_len = math.hypot(bx - ax, by - ay)
            if ab_len < 1.0:
                continue
            perp = abs((mx - ax) * (by - ay) - (my - ay) * (bx - ax)) / ab_len
            if perp <= 250.0:
                # Avoid creating parallel edge if (a, b) already exists
                if any(nb == b for nb, _ in adj[a]):
                    continue
                adj[a].remove((mid, w1))
                adj[b].remove((mid, w2))
                del adj[mid]
                adj[a].append((b, w1))
                adj[b].append((a, w1))
                changed = True
                break

    out = []
    seen = set()
    for u, nbs in adj.items():
        for v, w in nbs:
            key = (min(u, v), max(u, v))
            if key not in seen:
                seen.add(key)
                out.append((key[0], key[1], w))
    return out


def prune_board_tracks(board: pcbnew.BOARD) -> dict[str, int]:
    cu_layers = list(board.GetEnabledLayers().CuStack())
    for item in board.GetTracks():
        if item.GetClass() == "PCB_VIA":
            item.SetViaType(pcbnew.VIATYPE_THROUGH)
            item.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    before_unconn = board.GetConnectivity().GetUnconnectedCount(False)

    # Filled zone islands per (net_code, layer)
    zone_polys: dict[tuple[int, int], list[Polygon]] = defaultdict(list)
    for zone in board.Zones():
        if zone.GetIsRuleArea():
            continue
        nc = zone.GetNetCode()
        if nc <= 0:
            continue
        for lyr in cu_layers:
            if zone.IsOnLayer(lyr):
                ps = zone.GetFilledPolysList(lyr)
                for i in range(ps.OutlineCount()):
                    if ps.Outline(i).PointCount() >= 3:
                        zone_polys[(nc, lyr)].append(poly_from_outline(ps, i).buffer(0.002))

    # Group pads by net_code, merging physically overlapping sub-pads of the same footprint (e.g. U1-9 thermal vias)
    pads_by_net: dict[int, list[pcbnew.PAD]] = defaultdict(list)
    for fp in board.Footprints():
        for pad in fp.Pads():
            if pad.GetNetCode() > 0:
                pads_by_net[pad.GetNetCode()].append(pad)

    tracks_by_net: dict[int, list[pcbnew.PCB_TRACK]] = defaultdict(list)
    vias_by_net: dict[int, list[pcbnew.PCB_VIA]] = defaultdict(list)
    for tr in list(board.GetTracks()):
        if tr.IsLocked() or tr.GetNetCode() <= 0:
            continue
        if tr.GetClass() == "PCB_VIA":
            vias_by_net[tr.GetNetCode()].append(tr)
        elif tr.GetClass() == "PCB_TRACK":
            tracks_by_net[tr.GetNetCode()].append(tr)

    stats = {"tracks_before": 0, "tracks_after": 0, "vias_before": 0, "vias_after": 0, "cycles_broken": 0, "stubs_pruned": 0}

    for nc in sorted(set(tracks_by_net) | set(vias_by_net)):
        net_tracks = tracks_by_net.get(nc, [])
        net_vias = vias_by_net.get(nc, [])
        net_pads = pads_by_net.get(nc, [])
        stats["tracks_before"] += len(net_tracks)
        stats["vias_before"] += len(net_vias)
        if not net_tracks and not net_vias:
            continue

        # Merge physically overlapping pads on the same footprint (e.g. thermal-via sub-pads)
        pad_uf = UnionFind()
        pad_shapes: list[dict[int, Polygon]] = []
        for idx, pad in enumerate(net_pads):
            pad_uf.find(idx)
            shapes = {}
            for lyr in cu_layers:
                if pad.IsOnLayer(lyr):
                    polys = item_polys_mm(pad, lyr)
                    if polys:
                        p = polys[0]
                        for extra in polys[1:]:
                            p = p.union(extra)
                        shapes[lyr] = p.buffer(0.003)
            pad_shapes.append(shapes)
        for i in range(len(net_pads)):
            fpi = net_pads[i].GetParentFootprint().GetReference()
            for j in range(i + 1, len(net_pads)):
                if net_pads[j].GetParentFootprint().GetReference() != fpi:
                    continue
                if any(
                    lyr in pad_shapes[i] and lyr in pad_shapes[j] and pad_shapes[i][lyr].intersects(pad_shapes[j][lyr])
                    for lyr in cu_layers
                ):
                    pad_uf.union(i, j)

        pad_groups: dict[int, dict[int, Polygon]] = defaultdict(dict)
        pad_centers_by_layer: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for idx, pad in enumerate(net_pads):
            gid = pad_uf.find(idx)
            pt = pad.GetPosition()
            for lyr, poly in pad_shapes[idx].items():
                pad_groups[gid][lyr] = pad_groups[gid][lyr].union(poly) if lyr in pad_groups[gid] else poly
                pad_centers_by_layer[lyr].append((pt.x, pt.y))

        via_pts = [(v.GetPosition().x, v.GetPosition().y, v.GetDrillValue(), v.GetWidth(pcbnew.F_Cu)) for v in net_vias]
        via_xy = [(vx, vy) for vx, vy, _, _ in via_pts]

        # Split planar tracks per copper layer
        layer_segs: dict[int, list[tuple[int, int, int, int, int]]] = defaultdict(list)
        for tr in net_tracks:
            s, e = tr.GetStart(), tr.GetEnd()
            if math.hypot(e.x - s.x, e.y - s.y) >= 200:
                layer_segs[tr.GetLayer()].append((s.x, s.y, e.x, e.y, tr.GetWidth()))

        split_by_layer: dict[int, list[tuple[int, int, int, int, int]]] = {}
        all_pts: list[tuple[int, int]] = list(via_xy)
        for lyr in cu_layers:
            all_pts.extend(pad_centers_by_layer[lyr])
            jpts = via_xy + pad_centers_by_layer[lyr]
            split = split_planar_segments(layer_segs.get(lyr, []), jpts)
            split_by_layer[lyr] = split
            for x0, y0, x1, y1, _ in split:
                all_pts.append((x0, y0))
                all_pts.append((x1, y1))

        if not all_pts:
            continue
        pt_to_cid, cid_coords = cluster_points(all_pts, TOL_NM)

        # Build 3D net graph: nodes are ('L', lyr, cid), ('PAD', gid), ('ZONE', lyr, zidx), ('VIA', vidx)
        # Edges: (weight, -width, eid, u_node, v_node, payload)
        graph_edges = []
        eid = 0

        # Deduplicate parallel split segments per layer
        dedup_layer_edges: dict[int, dict[tuple[int, int], int]] = defaultdict(dict)
        active_layer_cids: dict[int, set[int]] = defaultdict(set)
        for lyr, segs in split_by_layer.items():
            for x0, y0, x1, y1, w in segs:
                u, v = pt_to_cid[(x0, y0)], pt_to_cid[(x1, y1)]
                if u == v:
                    continue
                key = (min(u, v), max(u, v))
                dedup_layer_edges[lyr][key] = max(w, dedup_layer_edges[lyr].get(key, 0))
                active_layer_cids[lyr].add(u)
                active_layer_cids[lyr].add(v)

        for lyr, emap in dedup_layer_edges.items():
            for (u, v), w in sorted(emap.items()):
                ux, uy = cid_coords[u]
                vx, vy = cid_coords[v]
                dist_mm = pcbnew.ToMM(round(math.hypot(vx - ux, vy - uy)))
                eid += 1
                graph_edges.append((dist_mm + 1e-6, -w, eid, ("L", lyr, u), ("L", lyr, v), ("TRACK", lyr, u, v, w)))

        # Deduplicate vias at same cid
        unique_vias: dict[int, tuple[int, int]] = {}
        for vx, vy, drill, vw in via_pts:
            vcid = pt_to_cid[(vx, vy)]
            unique_vias[vcid] = (drill, vw)
            for lyr in cu_layers:
                active_layer_cids[lyr].add(vcid)

        for vcid, (drill, vw) in sorted(unique_vias.items()):
            vnode = ("VIA", vcid)
            for lyr in cu_layers:
                eid += 1
                graph_edges.append((0.35, -vw, eid, vnode, ("L", lyr, vcid), ("VIA_SPOKE", vcid, drill, vw)))

        # Pad & Zone attachments (zero-cost internal copper overlap)
        terminals = set()
        pinned_by_layer: dict[int, set[int]] = defaultdict(set)
        for gid, lshapes in sorted(pad_groups.items()):
            pnode = ("PAD", gid)
            terminals.add(pnode)
            for lyr, poly in lshapes.items():
                for cid in sorted(active_layer_cids[lyr]):
                    cx, cy = cid_coords[cid]
                    if poly.contains(Point(pcbnew.ToMM(cx), pcbnew.ToMM(cy))):
                        eid += 1
                        graph_edges.append((0.0, 0, eid, pnode, ("L", lyr, cid), None))
                        pinned_by_layer[lyr].add(cid)
                for zidx, zpoly in enumerate(zone_polys.get((nc, lyr), ())):
                    if poly.intersects(zpoly):
                        eid += 1
                        graph_edges.append((0.0, 0, eid, pnode, ("ZONE", lyr, zidx), None))

        for lyr in cu_layers:
            for zidx, zpoly in enumerate(zone_polys.get((nc, lyr), ())):
                znode = ("ZONE", lyr, zidx)
                for cid in sorted(active_layer_cids[lyr]):
                    cx, cy = cid_coords[cid]
                    if zpoly.contains(Point(pcbnew.ToMM(cx), pcbnew.ToMM(cy))):
                        eid += 1
                        graph_edges.append((0.0, 0, eid, znode, ("L", lyr, cid), None))
                        pinned_by_layer[lyr].add(cid)

        # Kruskal's MST to eliminate all same-net cycles
        graph_edges.sort(key=lambda item: (item[0], item[1], item[2]))
        mst_uf = UnionFind()
        kept_edges = []
        for wt, neg_w, edge_id, u_node, v_node, payload in graph_edges:
            if mst_uf.union(u_node, v_node):
                kept_edges.append((edge_id, u_node, v_node, payload))
            elif payload is not None and payload[0] == "TRACK":
                stats["cycles_broken"] += 1

        # Build adjacency for iterative dead-end stub pruning
        adj: dict[tuple, dict[tuple, tuple]] = defaultdict(dict)
        for edge_id, u_node, v_node, payload in kept_edges:
            adj[u_node][v_node] = (edge_id, payload)
            adj[v_node][u_node] = (edge_id, payload)

        # Drop components with <= 1 terminal
        visited = set()
        for start in list(adj):
            if start in visited:
                continue
            comp = []
            q = deque([start])
            visited.add(start)
            while q:
                cur = q.popleft()
                comp.append(cur)
                for nb in adj[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append(nb)
            if sum(1 for nd in comp if nd in terminals) <= 1:
                for nd in comp:
                    for nb, (_, payload) in list(adj[nd].items()):
                        if payload is not None and payload[0] == "TRACK":
                            stats["stubs_pruned"] += 1
                    adj[nd].clear()

        # Leaf pruning: peel any non-terminal node with degree <= 1
        leaf_q = deque(nd for nd in adj if nd not in terminals and len(adj[nd]) <= 1)
        while leaf_q:
            nd = leaf_q.popleft()
            if nd in terminals or len(adj[nd]) > 1:
                continue
            for nb in list(adj[nd]):
                _, payload = adj[nd].pop(nb)
                adj[nb].pop(nd, None)
                if payload is not None and payload[0] == "TRACK":
                    stats["stubs_pruned"] += 1
                if nb not in terminals and len(adj[nb]) <= 1:
                    leaf_q.append(nb)

        # Extract surviving tracks and vias (a via survives iff degree('VIA', vcid) >= 2)
        surviving_vias: dict[int, tuple[int, int]] = {}
        surviving_tracks: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        seen_eids = set()
        for u_node, nbs in adj.items():
            if u_node[0] == "VIA" and len(nbs) >= 2:
                vcid = u_node[1]
                surviving_vias[vcid] = unique_vias[vcid]
                for lyr in cu_layers:
                    pinned_by_layer[lyr].add(vcid)
            for v_node, (edge_id, payload) in nbs.items():
                if edge_id in seen_eids or payload is None:
                    continue
                seen_eids.add(edge_id)
                if payload[0] == "TRACK":
                    _, lyr, u_cid, v_cid, w = payload
                    surviving_tracks[lyr].append((u_cid, v_cid, w))

        # Re-merge collinear degree-2 track segments
        merged_tracks: dict[int, list[tuple[int, int, int]]] = {}
        for lyr, tlist in surviving_tracks.items():
            merged_tracks[lyr] = merge_collinear(tlist, cid_coords, pinned_by_layer[lyr])

        # Replace unlocked tracks & vias on this net
        net_info = board.FindNet(nc)
        for tr in net_tracks:
            board.RemoveNative(tr)
        for v in net_vias:
            board.RemoveNative(v)

        for vcid, (drill, vw) in sorted(surviving_vias.items()):
            vx, vy = cid_coords[vcid]
            nv = pcbnew.PCB_VIA(board)
            nv.SetPosition(pcbnew.VECTOR2I(vx, vy))
            nv.SetViaType(pcbnew.VIATYPE_THROUGH)
            nv.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            nv.SetDrill(drill)
            nv.SetWidth(vw)
            board.Add(nv)
            nv.SetNet(net_info)
            stats["vias_after"] += 1

        for lyr in sorted(merged_tracks):
            for u_cid, v_cid, w in merged_tracks[lyr]:
                ux, uy = cid_coords[u_cid]
                vx, vy = cid_coords[v_cid]
                nt = pcbnew.PCB_TRACK(board)
                nt.SetStart(pcbnew.VECTOR2I(ux, uy))
                nt.SetEnd(pcbnew.VECTOR2I(vx, vy))
                nt.SetWidth(w)
                nt.SetLayer(lyr)
                board.Add(nt)
                nt.SetNet(net_info)
                stats["tracks_after"] += 1

    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    after_unconn = board.GetConnectivity().GetUnconnectedCount(False)
    if after_unconn > before_unconn:
        raise RuntimeError(f"Track pruner increased unconnected count from {before_unconn} to {after_unconn}")
    return stats
