# Demo prompts — talking to the M17 motors

These are the natural-language prompts for the demo video / live demo, once the server is
connected to Claude Desktop (or any MCP client). With the mock backend they run with no
hardware; with the serial backend they drive real motors. The point: **no API knowledge,
no code — just plain English.**

## Warm-up (proves discovery + control)
1. "What motors do you have connected?"
   → calls `list_motors`, names x / y / z and their positions.
2. "Home everything."
   → `home` (all).
3. "Point the X axis to 90 degrees, smoothly over 2 seconds."
   → `trapezoid_move(x, 90, 2)`.
4. "Where is everything right now?"
   → `get_status`.

## The headline shot — "draw a square"
5. "Draw a square: move X and Y to trace a 90-degree box, then come back to the start."
   → Claude composes a `run_sequence` of `move_to`/`trapezoid_move` steps. This is the
     clip that goes in the launch posts — one sentence, real motion.

## Show full range of motion (great for the technical audience / HN comments)
6. "Spin Z to 720 degrees."
   → The server forwards the command straight to the motor — it makes two full turns and the
     closed-loop encoder confirms it settled at 720°. The MCP is a thin control layer with no
     software limits; the motor's own firmware protects it (over-current/voltage/temperature).

## The "talk to your hardware" moment
7. "Wave hello with the Z axis."
   → Claude improvises a small back-and-forth `run_sequence`. Good, human closer.

> Recording notes: pen plotter reads best on camera (see SPEC.md). Keep the terminal /
> Claude transcript on screen next to the hardware so viewers see prompt → tool call →
> motion. ~60–90s total. End on the square.
