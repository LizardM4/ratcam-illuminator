from __future__ import unicode_literals
import math
from collections import namedtuple

import pcbnew as pcb

# Leds will be named LED0, LED1...
LED_PREFIX = 'LED'
# Resistor driving LEDS will be named R0, R1, ...
RESISTOR_PREFIX = 'R'
# Other names
MOSFET_NAME = 'Q0'
PIN_NAME = 'J0'
# Coordinated of the center in mm
CENTER_X_MM = 100.
CENTER_Y_MM = 100.
# Radius of the circle where the center of the components
# (leds and resistor) is placed
RADIUS_MM = 30.
# Number of lines of LED (= number of resistors)
N_LINES = 3
# Number of leds per line
N_LEDS_PER_LINE = 3
# Offset angle for the whole design
ROTATION_OFS_RAD = -math.pi / 12.
# Offset angle of the LEDs
LED_ORIENTATION_OFS_RAD = math.pi
# Offset angle of the resistors
RESISTOR_ORIENTATION_OFS_RAD = 0.
# Angular resolution for synthesizing arcs
ANGULAR_RESOLUTION = math.pi / 40
# True for having the power ring on F.Cu (False resp. for B.Cu)
PWR_RING_FCU = True
# True for having the ground ring on F.Cu (False resp. for B.Cu)
GND_RING_FCU = True
# Radial offset in mm for the power ring
PWR_RING_DISP_MM = -4.
# Radial offset in mm for the ground ring
GND_RING_DISP_MM = 4.
# Extra portion of wire to add before connecting to a ring
_ANG_DIST_BTW_MODS = 2. * math.pi / float((1 + N_LEDS_PER_LINE) * N_LINES)
RING_OVERHANG_ANGLE = _ANG_DIST_BTW_MODS / 3.
# If >0, routes the LED strips with a copper fill
LED_FILL_WIDTH_MM = 4.
DEFAULT_TRACK_WIDTH_MM=1.

MOSFET_ORIENTATION = 0.
PIN_ORIENTATION = 0.

_RESIDUAL_ANGLE = (_ANG_DIST_BTW_MODS - 2. * RING_OVERHANG_ANGLE)
_TARGET_REMAINING_ANGLE = 2. * math.asin((-min(PWR_RING_DISP_MM, GND_RING_DISP_MM) - LED_FILL_WIDTH_MM / 2. - DEFAULT_TRACK_WIDTH_MM / 2.) / (2. * RADIUS_MM))
_FILL_OVERHANG_ANGLE = (_RESIDUAL_ANGLE - _TARGET_REMAINING_ANGLE) / 2.

Terminal = namedtuple('Terminal', ['module', 'pad'])

LayerBCu = 31
LayerFCu = 0
NetTypeLedStrip = 'led strip'
NetTypePower = 'power'
NetTypeGround = 'ground'
NetTypeUnknown = '?'


Place = namedtuple('Place', ['x', 'y', 'rot'])


def ortho(a):
    return a - math.pi / 2.

def to_cartesian(c, angle, r):
    return c.__class__(c.x + r * math.cos(angle), c.y + r * math.sin(angle))

def to_polar(c, pos):
    pos_dx = pos.x - c.x
    pos_dy = pos.y - c.y
    r = math.sqrt(pos_dx * pos_dx + pos_dy * pos_dy)
    angle = math.acos(pos_dx / r)
    if pos_dy < 0.: angle = 2. * math.pi - angle
    return (angle, r)

def shift_along_radius(c, pos, shift):
    delta = pos - c
    radius = math.sqrt(delta.x * delta.x + delta.y * delta.y)
    scale_factor = float(shift) / radius
    return pos + pos.__class__(delta.x * scale_factor, delta.y * scale_factor)

def shift_along_arc(c, pos, delta_angle):
    angle, r = to_polar(c, pos)
    return to_cartesian(c, angle + delta_angle, r)

def compute_radial_segment(c, start, end=None, angle=None, steps=None, angular_resolution=None, excess_angle=0., skip_start=True):
    assert((end is None) != (angle is None))
    # Determine polar coordinates of start
    start_angle, start_r = to_polar(c, start)

    if end is None:
        end_r = start_r
        end_angle = start_angle + angle
    else:
        end_angle, end_r = to_polar(c, end)

    # Choose the arc < 180 degrees
    if abs(end_angle - start_angle) > math.pi:
        if start_angle < end_angle:
            end_angle -= 2. * math.pi
        else:
            start_angle -= 2. * math.pi
    assert((steps is None) != (angular_resolution is None))
    if steps is None:
        steps = int(math.ceil(abs(end_angle - start_angle) / angular_resolution))
    steps = max(1, steps)
    if excess_angle != 0.:
        if start_angle <= end_angle:
            start_angle -= excess_angle
            end_angle += excess_angle
        else:
            start_angle += excess_angle
            end_angle -= excess_angle
    for i in range(steps + 1):
        frac = float(i) / float(steps)
        angle = start_angle + frac * (end_angle - start_angle)
        r = start_r + frac * (end_r - start_r)
        if i > 0 or not skip_start:
            yield to_cartesian(c, angle, r)


class Illuminator(object):

    def guess_net_type(self, terminals):
        all_leds = True
        all_resistors = True
        for t in terminals:
            if t.module.startswith(LED_PREFIX):
                all_resistors = False
            elif t.module.startswith(RESISTOR_PREFIX):
                all_leds = False
        if all_leds != all_resistors:
            if all_resistors:
                # 2+ resistors connected: power
                return NetTypePower
            elif len(terminals) != 2:
                # 1 or 3+ led connected: ground
                return NetTypeGround
            else:
                # If it's the same pad, it's ground,
                # otherwise, Strip
                if terminals[0].pad == terminals[1].pad:
                    return NetTypeGround
                else:
                    return NetTypeLedStrip
        elif not all_leds and len(terminals) == 2:
            # Mixed resistor/led 2-terminal net. That's a strip
            return NetTypeLedStrip
        else:
            return NetTypeUnknown


    def get_nets_at_placed_modules(self):
        retval = {}
        for mod_name in self.placed_modules:
            mod = self.board.FindModule(mod_name)
            for pad in mod.Pads():
                net = pad.GetNet()
                net_code = pad.GetNetCode()
                if net_code not in retval:
                    retval[net_code] = []
                retval[net_code].append(Terminal(module=mod_name, pad=pad.GetPadName()))
        return retval

    def clear_tracks_in_nets(self, net_codes):
        for track in self.board.GetTracks():
            if track.GetNetCode() in net_codes:
                self.board.Delete(track)
        to_delete = []
        for i in range(self.board.GetAreaCount()):
            area = self.board.GetArea(i)
            if area.GetNetCode() in net_codes:
                to_delete.append(area)
        for area in to_delete:
            self.board.Delete(area)

    def place_module(self, name, place):
        mod = self.board.FindModule(name)
        if mod:
            print('Placing %s at %s.' % (name, str(place)))
            mod.SetPosition(pcb.wxPoint(place.x, place.y))
            mod.SetOrientation(-math.degrees(place.rot) * 10.)

    def get_terminal_position(self, terminal):
        return self.board.FindModule(terminal.module).FindPadByName(terminal.pad).GetPosition()

    def get_module_position(self, module):
        return self.board.FindModule(module).GetPosition()

    def get_net_name(self, net_code):
        return self.board.FindNet(net_code).GetNetname()

    def _get_one_place(self, angle, orientation=0.):
        return Place(
            x=self.center.x + pcb.FromMM(RADIUS_MM) * math.cos(angle + ROTATION_OFS_RAD),
            y=self.center.y + pcb.FromMM(RADIUS_MM) * math.sin(angle + ROTATION_OFS_RAD),
            rot=ortho(angle + ROTATION_OFS_RAD) + orientation
        )

    def place(self):
        n_elm = N_LINES * (1 + N_LEDS_PER_LINE)
        angle_step = 2. * math.pi / float(n_elm)
        angle = 0.
        for line_idx in range(N_LINES):
            mod_name = RESISTOR_PREFIX + str(line_idx)
            self.place_module(mod_name,
                self._get_one_place(angle, RESISTOR_ORIENTATION_OFS_RAD))
            angle -= angle_step
            self.placed_modules.add(mod_name)
            for led_idx in range(N_LEDS_PER_LINE):
                mod_name = LED_PREFIX + str(line_idx * N_LEDS_PER_LINE + led_idx)
                self.place_module(LED_PREFIX + str(line_idx * N_LEDS_PER_LINE + led_idx),
                    self._get_one_place(angle, LED_ORIENTATION_OFS_RAD))
                angle -= angle_step
                self.placed_modules.add(mod_name)
        self._place_pin_and_fet()

    def make_track_segment(self, start, end, net_code, layer):
        t = pcb.TRACK(self.board)
        self.board.Add(t)
        t.SetStart(start)
        t.SetEnd(end)
        t.SetNetCode(net_code)
        t.SetLayer(layer)
        t.SetWidth(pcb.FromMM(DEFAULT_TRACK_WIDTH_MM))
        return end

    def make_track_horizontal_segment_to_radius(self, start, radius, net_code, layer):
        angle = math.asin(float(start.y - self.center.y) / radius)
        if start.x < self.center.x: angle = math.pi - angle
        end = pcb.wxPoint(self.center.x + radius * math.cos(angle), start.y)
        return self.make_track_segment(start, end, net_code, layer)

    def _make_track_arc_internal(self, start, net_code, layer, *args, **kwargs):
        last = start
        for pt in compute_radial_segment(self.center, start, *args, **kwargs):
            self.make_track_segment(last, pt, net_code, layer)
            last = pt
        return last

    def make_track_arc_from_endpts(self, start, end, net_code, layer):
        return self._make_track_arc_internal(
            start, net_code, layer,
            end=end, angular_resolution=ANGULAR_RESOLUTION)

    def make_track_arc_from_angle(self, start, angle, net_code, layer):
        return self._make_track_arc_internal(
            start, net_code, layer,
            angle=angle, angular_resolution=ANGULAR_RESOLUTION)

    def make_track_radial_segment(self, pos, displacement, net_code, layer):
        end_pos = shift_along_radius(self.center, pos, displacement)
        return self.make_track_segment(pos, end_pos, net_code, layer)

    def make_fill_area(self, vertices, is_thermal, net_code, layer):
        area = self.board.InsertArea(net_code, self.board.GetAreaCount(), layer,
            vertices[0].x, vertices[0].y, pcb.CPolyLine.DIAGONAL_EDGE)
        if is_thermal:
            area.SetPadConnection(pcb.PAD_ZONE_CONN_THERMAL)
        else:
            area.SetPadConnection(pcb.PAD_ZONE_CONN_FULL)
        # area.SetIsFilled(True)
        outline = area.Outline()
        for vertex in vertices[1:]:
            if getattr(outline, 'AppendCorner', None) is None:
                # Kicad nightly
                outline.Append(vertex.x, vertex.y)
            else:
                outline.AppendCorner(vertex.x, vertex.y)
        if getattr(outline, 'CloseLastContour', None) is not None:
            outline.CloseLastContour()
        area.SetCornerRadius(pcbnew.FromMM(DEFAULT_TRACK_WIDTH_MM / 2.))
        area.SetCornerSmoothingType(pcb.ZONE_SETTINGS.SMOOTHING_FILLET)
        area.BuildFilledSolidAreasPolygons(self.board)
        return area

    def make_fill_arc(self, start, end, width, is_thermal, net_code, layer):
        # Compute the vertices
        lower_arc_start = shift_along_radius(self.center, start, -width / 2.)
        upper_arc_start = shift_along_radius(self.center, end, width / 2.)
        vertices = list(compute_radial_segment(self.center,
                lower_arc_start,
                shift_along_radius(self.center, end, -width / 2.),
                angular_resolution=ANGULAR_RESOLUTION,
                excess_angle=0.0001,
                skip_start=False)) + \
            list(compute_radial_segment(self.center,
                upper_arc_start,
                shift_along_radius(self.center, start, width / 2.),
                angular_resolution=ANGULAR_RESOLUTION,
                excess_angle=0.0001,
                skip_start=False))
        return self.make_fill_area(vertices, is_thermal, net_code, layer)

    def make_via(self, position, net_code):
        v = pcb.VIA(self.board)
        self.board.Add(v)
        v.SetPosition(position)
        v.SetViaType(pcb.VIA_THROUGH)
        v.SetLayerPair(LayerFCu, LayerBCu)
        v.SetNetCode(net_code)
        v.SetWidth(pcb.FromMM(DEFAULT_TRACK_WIDTH_MM))
        return position

    def _route_arc(self, net_code, start_terminal, end_terminal, layer=LayerFCu):
        print('Routing %s between %s and %s with a single arc.' % (
            self.get_net_name(net_code), start_terminal.module, end_terminal.module
        ))
        # Get the offsetted position of the pads
        self.make_track_arc_from_endpts(
            self.get_terminal_position(start_terminal),
            self.get_terminal_position(end_terminal),
            net_code,
            layer
        )

    def _route_fill_arc(self, net_code, start_terminal, end_terminal):
        print('Routing %s between %s and %s with filled arc region.' % (
            self.get_net_name(net_code), start_terminal.module, end_terminal.module
        ))
        start_pos = self.get_terminal_position(start_terminal)
        end_pos = self.get_terminal_position(end_terminal)
        self.make_track_arc_from_endpts(
            start_pos,
            end_pos,
            net_code,
            LayerFCu
        )
        # Get the offsetted position of the pads
        self.make_fill_arc(
            start_pos,
            end_pos,
            pcb.FromMM(LED_FILL_WIDTH_MM),
            False,
            net_code,
            LayerFCu
        )

    def _route_ring(self, net_code, terminals, displacement, ring_overhang, layer):
        log_msg = 'Routing %s between %s with' % (
            self.get_net_name(net_code), ', '.join([t.module for t in terminals])
        )
        if layer != LayerFCu:
            log_msg += ' a via and'
        if displacement == 0.:
            log_msg += ' a full circular track.'
        else:
            log_msg += ' a circular track offsetted by %f.' % displacement
        terminal_pos = []
        for terminal in terminals:
            term_ring_pt = self.get_terminal_position(terminal)
            _, term_ring_pt_r = to_polar(self.center, term_ring_pt)
            if displacement != 0.:
                if ring_overhang != 0.:
                    mod_pos_angle, _ = to_polar(self.center,
                        self.get_module_position(terminal.module))
                    new_end_pt = to_cartesian(self.center,
                        mod_pos_angle + ring_overhang, term_ring_pt_r)
                    self.make_track_arc_from_endpts(term_ring_pt, new_end_pt, net_code, LayerFCu)
                    if LED_FILL_WIDTH_MM != 0.:
                        # Some extra fill:
                        overhang_angle = _FILL_OVERHANG_ANGLE * (1. if ring_overhang > 0. else -1.)
                        fill_end_pt  = shift_along_arc(self.center,
                            new_end_pt, overhang_angle)
                        self.make_fill_arc(term_ring_pt, fill_end_pt,
                            pcb.FromMM(LED_FILL_WIDTH_MM),
                            False, net_code, LayerFCu)
                    term_ring_pt = new_end_pt
                term_ring_pt = self.make_track_radial_segment(
                    term_ring_pt, displacement, net_code, LayerFCu)
            # Now add the via and store the position
            if layer != LayerFCu:
                self.make_via(term_ring_pt, net_code)
            terminal_pos.append(term_ring_pt)
        # Connect the terminals with an arc. Make sure
        # that all the positions at 0 and 180 are covered
        polar_term_pos = [to_polar(self.center, pos) for pos in terminal_pos]
        polar_term_pos += [
            (0, pcb.FromMM(RADIUS_MM) + displacement),
            (math.pi, pcb.FromMM(RADIUS_MM) + displacement)
        ]
        polar_term_pos.sort()

        # Now make the actual tracks. One more cartesian/polar conversion
        # because I didn't really think this through
        last_pos = polar_term_pos[-1]
        for pos in polar_term_pos:
            self.make_track_arc_from_endpts(
                to_cartesian(self.center, *last_pos),
                to_cartesian(self.center, *pos),
                net_code, layer)
            last_pos = pos

    def route(self):
        for net_code, terminals in self.get_nets_at_placed_modules().items():
            # Try to guess net type
            net_type = self.guess_net_type(terminals)
            print('Net %s guessed type: %s' % (self.get_net_name(net_code), net_type))
            if net_type == NetTypeUnknown:
                print('I do not know what to to with net %s between %s...' % (
                    self.get_net_name(net_code),
                    str(terminals)
                ))
                continue
            # Clear this net
            self.clear_tracks_in_nets([net_code])
            if net_type == NetTypeLedStrip:
                assert(len(terminals) == 2)
                if LED_FILL_WIDTH_MM > 0.:
                    self._route_fill_arc(net_code, terminals[0], terminals[1])
                else:
                    self._route_arc(net_code, terminals[0], terminals[1])
            elif net_type == NetTypePower:
                assert(self.power_net is None)
                self.power_net = net_code
                self._route_ring(net_code, terminals,
                    pcb.FromMM(PWR_RING_DISP_MM),
                    RING_OVERHANG_ANGLE,
                    LayerFCu if PWR_RING_FCU else LayerBCu
                )
            elif net_type == NetTypeGround:
                assert(self.ground_net is None)
                self.ground_net = net_code
                self._route_ring(net_code, terminals,
                    pcb.FromMM(GND_RING_DISP_MM),
                    -RING_OVERHANG_ANGLE,
                    LayerFCu if GND_RING_FCU else LayerBCu
                )
        self._route_pin_and_fet()

    def _place_pin_and_fet(self):
        self.pin = self.board.FindModule(PIN_NAME)
        self.fet = self.board.FindModule(MOSFET_NAME)
        if self.pin is None or self.fet is None:
            return
        # Ok place first the pin centered and rotated
        if not self.pin.IsFlipped():
            self.pin.Flip(self.pin.GetPosition())
        if not self.fet.IsFlipped():
            self.fet.Flip(self.pin.GetPosition())
        print('Found pin and mosfet, placing them at opposite sides of the board.')
        self.place_module(self.pin.GetReference(),
            Place(self.center.x - pcb.FromMM(RADIUS_MM), self.center.y, PIN_ORIENTATION))
        self.place_module(self.fet.GetReference(),
            Place(self.center.x + pcb.FromMM(RADIUS_MM), self.center.y, MOSFET_ORIENTATION))

    def _route_pin_and_fet(self):
        if self.pin is None or self.fet is None:
            return
        print('Found pin and mosfet, adding connection rings')
        routed_nets = set()
        for pin_pad in self.pin.Pads():
            for fet_pad in self.fet.Pads():
                if fet_pad.GetNetCode() != pin_pad.GetNetCode(): continue
                net_code = fet_pad.GetNetCode()
                routed_nets.add(net_code)
                self.clear_tracks_in_nets([net_code])
                # Make a horizontal segment to the right radius
                fet_pt = self.make_track_horizontal_segment_to_radius(
                    fet_pad.GetPosition(), pcb.FromMM(RADIUS_MM), net_code, LayerBCu)
                pin_pt = self.make_track_horizontal_segment_to_radius(
                    pin_pad.GetPosition(), pcb.FromMM(RADIUS_MM), net_code, LayerBCu)
                print('Adding ring from the mosfet pad %s (net %s)' % (
                    fet_pad.GetName(), self.get_net_name(net_code)))
                self.make_track_arc_from_endpts(fet_pt, pin_pt, net_code, LayerBCu)
        print('Adding missing vias to known nets.')
        # Find the third pad
        for pad in self.fet.Pads():
            if pad.GetNetCode() != self.ground_net: continue
            print('Connecting pad %s of the mosfet to net %s' % (
                pad.GetName(), self.get_net_name(self.ground_net)))
            # We know there is a point in this net at theta = 0
            # Drop a via from there
            known_pt = to_cartesian(self.center, 0.,
                pcb.FromMM(RADIUS_MM + GND_RING_DISP_MM))
            self.make_via(known_pt, self.ground_net)
            # and then straight to this pad
            self.make_track_segment(
                known_pt, pad.GetPosition(),
                self.ground_net, LayerBCu)
        # Find the third pin
        for pad in self.pin.Pads():
            if pad.GetNetCode() != self.power_net: continue
            print('Connecting pad %s of the mosfet to net %s' % (
                pad.GetName(), self.get_net_name(self.power_net)))
            # We know there is a point in this net at theta=180
            # Drop a via from there
            known_pt = to_cartesian(self.center, math.pi,
                pcb.FromMM(RADIUS_MM + PWR_RING_DISP_MM))
            self.make_via(known_pt, self.power_net)
            # and then straight to this pad
            self.make_track_segment(
                known_pt, pad.GetPosition(),
                self.power_net, LayerBCu)


    def __init__(self):
        super(Illuminator, self).__init__()
        self.placed_modules = set()
        self.board = pcb.GetBoard()
        self.center = pcb.wxPoint(pcb.FromMM(CENTER_X_MM), pcb.FromMM(CENTER_Y_MM))
        self.pin = None
        self.fet = None
        self.ground_net = None
        self.power_net = None

if __name__ == '__main__':
    a = Illuminator()
    a.place()
    a.route()
