from trio_kit.tui.canvas import Canvas, HitMap, Rect


def test_canvas_primitives_clip_text_and_keep_one_cell_geometry() -> None:
    canvas = Canvas(8, 4)
    canvas.box(0, 0, 8, 4, style="ascii", role="border")
    canvas.fill(1, 1, 3, 1, char=".", role="muted")
    canvas.hline(1, 2, 5, char="=", role="accent")
    canvas.vline(6, 1, 2, char="!", role="warning")

    assert canvas.put(1, 1, "A") is True
    assert canvas.put(2, 1, "界") is False
    assert canvas.put(2, 1, "\x1b") is False
    canvas.text(1, 1, "A界B", role="text")
    canvas.text_center(2, "xy", x=0, width=8)
    canvas.blit_art(6, 1, ("Z界", "Q"), role="title")

    assert canvas.snapshot().splitlines() == [
        "+------+",
        "|A?B  Z?",
        "|==xy=Q|",
        "+------+",
    ]
    assert {len(row) for row in canvas.snapshot().splitlines()} == {8}


def test_canvas_clips_drawing_and_hit_rectangles() -> None:
    canvas = Canvas(5, 3)
    with canvas.clipped(Rect(1, 1, 3, 1)):
        canvas.fill(0, 0, 5, 3, char="x")
        canvas.text(-4, 1, "abcdef")
        canvas.hit(0, 0, 5, 3, "clipped")

    assert canvas.snapshot() == "     \n fxx \n     "
    assert canvas.hit_map.regions[0].rect == Rect(1, 1, 3, 1)
    assert canvas.hit_map.at(1, 1).tag == "clipped"
    assert canvas.hit_map.at(0, 1) is None


def test_hitmap_checks_each_cell_and_newer_overlap_is_topmost() -> None:
    hit_map = HitMap(6, 4)
    hit_map.add(Rect(0, 0, 4, 3), "under")
    hit_map.add(Rect(2, 1, 3, 2), "over")

    for y in range(4):
        for x in range(6):
            hit = hit_map.at(x, y)
            if 2 <= x < 5 and 1 <= y < 3:
                assert hit is not None and hit.tag == "over"
            elif x < 4 and y < 3:
                assert hit is not None and hit.tag == "under"
            else:
                assert hit is None
    assert hit_map.at(-1, 0) is None
    assert hit_map.at(6, 3) is None


def test_empty_and_outside_hit_rectangles_are_ignored() -> None:
    hit_map = HitMap(4, 2)
    assert hit_map.add(Rect(1, 1, 0, 1), "empty") is None
    assert hit_map.add(Rect(8, 4, 2, 2), "outside") is None
    assert hit_map.regions == ()


def test_ascii_canvas_substitutes_unicode_and_uses_ascii_frames() -> None:
    canvas = Canvas(8, 3, ascii_only=True)
    canvas.box(0, 0, 8, 3, style="round")
    canvas.text(1, 1, "café界")
    assert canvas.snapshot().splitlines() == ["+------+", "|caf?? |", "+------+"]
