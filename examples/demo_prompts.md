# Demo prompts — talking to the M17 motors

These are the natural-language prompts for the demo video / live demo, once the server is
connected to Claude Desktop (or any MCP client). With the mock backend they run with no
hardware; with the serial backend they drive real motors. The point: **no API knowledge,
no configuration, no code — just plain English.**

## Zero-config discovery (the new opener — nothing is hardcoded)
1. "Find my motors."
   → Claude calls `list_serial_ports`, picks the USB-RS485 adapter (or asks you which),
     `connect`s, and the bus auto-detection reports every motor's alias + unique ID.
     If there are several adapters, it checks them until motors turn up.
2. "What state is it in?"
   → `list_motors` / `get_motor_status`: live position, supply voltage, temperature,
     and any fault decoded to plain English.

## Warm-up (proves control)
3. "Rotate motor 88 to 90 degrees."
   → `move_to(88, 90)` — closed-loop, waits until settled.
4. "Now back off 30 degrees, gently."
   → `move_relative(88, -30, slow speed)`.

## The headline shot — "draw a square"
5. "Draw a square: move X and Y to trace a 90-degree box, then come back to the start."
   → Claude composes a `run_sequence`. This is the clip that goes in the launch posts —
     one sentence, real motion.

## Show full range of motion (great for the technical audience / HN comments)
6. "Spin it 720 degrees."
   → Straight to the motor — two full turns, encoder-confirmed. No software limits; the
     motor's own firmware protects it (over-current/voltage/temperature).

## Deep cuts (the full command set is exposed)
7. "Blink its LED so I know which one it is." → `identify`.
8. "Make it vibrate for a second." → `vibrate(1)` … `vibrate(0)`.
9. "What's the firmware version and product info?" → `get_firmware_version`, `get_product_info`.
10. "Zero it here, then do a smooth velocity ramp: accelerate for one second, decelerate
    for one second." → `zero_position` + `multimove` (acceleration moves).

## The "talk to your hardware" moment
11. "Wave hello."
    → Claude improvises a small back-and-forth `run_sequence`. Good, human closer.

> Recording notes: pen plotter reads best on camera (see SPEC.md). Keep the terminal /
> Claude transcript on screen next to the hardware so viewers see prompt → tool call →
> motion. ~60–90s total. End on the square.
