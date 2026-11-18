"""Render colored 3D enclosure views (base, lid, assembly) via offscreen VTK (`cad` container)."""

import re
import sys
from pathlib import Path

import cadquery as cq
import vtk

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "mechanical/scripts"))
import build_enclosure as be

BUILD = REPO / "mechanical/build/v1"
OUT = BUILD / "renders"

BASE_RGB = (0.28, 0.30, 0.34)
LID_RGB = (0.68, 0.71, 0.75)
LEGEND_RGB = (0.12, 0.13, 0.15)
LED_RGB = (0.22, 0.72, 0.38)

SVG_OPT = {
    "width": 1000,
    "height": 750,
    "marginLeft": 30,
    "marginTop": 30,
    "showAxes": False,
    "projectionDir": (-1.75, 1.1, 5.0),
    "strokeWidth": 0.45,
    "strokeColor": (20, 20, 20),
    "hiddenColor": (180, 180, 180),
    "showHidden": True,
}


def fix_svg_canvas(svg_path: Path) -> None:
    text = svg_path.read_text()
    m_tf = re.search(r'transform="scale\(([^,]+),\s*([^)]+)\)\s*translate\(([^,]+),\s*([^)]+)\)"', text)
    nums = re.findall(r"[ML](-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    if m_tf and nums:
        sx, sy, tx, ty = (float(v) for v in m_tf.groups())
        xs = [(float(x) + tx) * sx for x, _ in nums]
        ys = [(float(y) + ty) * sy for _, y in nums]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        pad = max(x1 - x0, y1 - y0) * 0.08
        vx, vy, vw, vh = x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
        text = re.sub(
            r'width="[^"]+"\s*height="[^"]+"',
            f'width="1000" height="750" viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}"',
            text,
            count=1,
        )
        bg = f'\n  <rect x="{vx:.2f}" y="{vy:.2f}" width="{vw:.2f}" height="{vh:.2f}" fill="#ffffff"/>'
    else:
        bg = '\n  <rect width="100%" height="100%" fill="#ffffff"/>'
    text = re.sub(r"(<svg\b[^>]*>)", r"\1" + bg, text, count=1)
    svg_path.write_text(text)


def make_actor(shape: cq.Workplane, rgb: tuple[float, float, float], opacity: float = 1.0) -> vtk.vtkActor:
    vertices, faces = shape.val().tessellate(0.08, 0.15)
    points = vtk.vtkPoints()
    for v in vertices:
        points.InsertNextPoint(v.x, v.y, v.z)
    polys = vtk.vtkCellArray()
    for face in faces:
        polys.InsertNextCell(3, face)
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    data.SetPolys(polys)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(data)
    normals.SetFeatureAngle(35)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*rgb)
    actor.GetProperty().SetOpacity(opacity)
    actor.GetProperty().SetDiffuse(0.78)
    actor.GetProperty().SetSpecular(0.18)
    actor.GetProperty().SetSpecularPower(22)
    return actor


def render_colored_png(name: str, items: list[tuple[cq.Workplane, tuple[float, float, float], float]]) -> None:
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(1.0, 1.0, 1.0)
    for shape, rgb, opacity in items:
        renderer.AddActor(make_actor(shape, rgb, opacity))

    light_key = vtk.vtkLight()
    light_key.SetPosition(-120, 80, 180)
    light_key.SetFocalPoint(be.PCB_W / 2, be.PCB_H / 2, 10)
    light_key.SetIntensity(0.85)
    renderer.AddLight(light_key)

    light_fill = vtk.vtkLight()
    light_fill.SetPosition(140, -90, 120)
    light_fill.SetFocalPoint(be.PCB_W / 2, be.PCB_H / 2, 10)
    light_fill.SetIntensity(0.45)
    renderer.AddLight(light_fill)

    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetMultiSamples(4)
    win.SetSize(1200, 900)
    win.AddRenderer(renderer)

    cam = renderer.GetActiveCamera()
    cx, cy, cz = be.PCB_W / 2, be.PCB_H / 2, 9.0
    cam.SetFocalPoint(cx, cy, cz)
    cam.SetPosition(cx - 105, cy + 65, cz + 145)
    cam.SetViewUp(0, 1, 0)
    renderer.ResetCamera()
    cam.Zoom(1.18)
    win.Render()

    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(OUT / f"{name}.png"))
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()


def render_svg(shape: cq.Workplane, name: str, *, show_hidden: bool = True) -> None:
    svg_path = OUT / f"{name}.svg"
    opt = dict(SVG_OPT, showHidden=show_hidden)
    cq.exporters.export(shape, str(svg_path), exportType="SVG", opt=opt)
    fix_svg_canvas(svg_path)


def lid_legend_inlay() -> list[tuple[cq.Workplane, tuple[float, float, float], float]]:
    items = [(s, LEGEND_RGB, 1.0) for s in be.make_lid_legend_solids(be.Z_LID_TOP - 0.01, 0.42)]
    for lx, ly in (be.LED_NET_XY, be.LED_GATE_XY):
        glow = cq.Workplane("XY").workplane(offset=be.Z_LID_TOP - 0.15).center(lx, ly).circle(1.3).extrude(0.16)
        items.append((glow, LED_RGB, 0.75))
    return items


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base_step = BUILD / "base.step"
    lid_step = BUILD / "lid.step"
    if not (base_step.exists() and lid_step.exists()):
        raise FileNotFoundError("Run build_enclosure.py before render_assembly3d.py")

    base_s = cq.importers.importStep(str(base_step))
    lid_s = cq.importers.importStep(str(lid_step))
    legend = lid_legend_inlay()

    render_svg(base_s, "base", show_hidden=True)
    render_colored_png("base", [(base_s, BASE_RGB, 1.0)])

    render_svg(lid_s, "lid", show_hidden=True)
    render_colored_png("lid", [(lid_s, LID_RGB, 1.0)] + legend)

    closed = cq.Workplane("XY").newObject(
        [cq.Compound.makeCompound(list(base_s.solids().vals()) + list(lid_s.solids().vals()))]
    )
    render_svg(closed, "assembly", show_hidden=False)
    render_colored_png("assembly", [(base_s, BASE_RGB, 1.0), (lid_s, LID_RGB, 1.0)] + legend)

    print(f"Rendered colored enclosure views -> {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
