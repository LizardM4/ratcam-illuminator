from __future__ import unicode_literals
from collections import namedtuple
import math


Place = namedtuple('Place', ['x', 'y', 'rot'])


def ortho(a):
    return a - math.pi / 2.


def radial_segment(c_x, c_y, start_x, start_y, end_x, end_y, steps):
    # Distances from the origin
    start_dx = start_x - c_x
    start_dy = start_y - c_y
    end_dx = end_x - c_x
    end_dy = end_y - c_y
    start_r = math.sqrt(start_dx * start_dx + start_dy * start_dy)
    end_r = math.sqrt(end_dx * end_dx + end_dy * end_dy)
    # Angles
    start_angle = math.acos(start_dx / start_r)
    end_angle = math.acos(end_dx / end_r)
    if start_dy < 0.: start_angle = 2. * math.pi - start_angle
    if end_dy < 0.: end_angle = 2. * math.pi - end_angle
    # Choose the arc < 180 degrees
    if abs(end_angle - start_angle) > math.pi:
        if start_angle < end_angle:
            end_angle -= 2. * math.pi
        else:
            start_angle -= 2. * math.pi
    for i in range(steps):
        frac = float(i) / float(steps)
        angle = start_angle + frac * (end_angle - start_angle)
        r = start_r + frac * (end_r - start_r)
        x = c_x + r * math.cos(angle)
        y = c_y + r * math.sin(angle)
        yield (x, y)


class Illuminator(object):

    def get_resistor_name(self, line_idx):
        return 'R%d' % (line_idx)

    def get_led_name(self, line_idx, led_idx):
        return 'LED%d' % (line_idx * self.n_leds_per_line + led_idx)

    def get_one_place(self, angle, orientation=0.):
        return Place(
            x=self.center.x + self.radius * math.cos(angle + self.center.rot),
            y=self.center.y + self.radius * math.sin(angle + self.center.rot),
            rot=ortho(angle) + orientation
        )

    def __call__(self):
        # Total number of elements
        n_elm = self.n_lines * (1 + self.n_leds_per_line)
        angle_step = 2. * math.pi / float(n_elm)
        angle = 0.
        for line_idx in range(self.n_lines):
            yield (self.get_resistor_name(line_idx), self.get_one_place(angle))
            angle -= angle_step
            for led_idx in range(self.n_leds_per_line):
                yield (self.get_led_name(line_idx, led_idx),
                    self.get_one_place(angle, orientation=self.led_orientation))
                angle -= angle_step

    def __init__(self,
                n_lines=3,
                n_leds_per_line=3,
                radius=30.,
                center=Place(x=100., y=100., rot=0.),
                led_orientation=math.pi
            ):
        super(Illuminator, self).__init__()
        self.n_leds_per_line = n_leds_per_line
        self.n_lines = n_lines
        self.center = center
        self.radius = radius
        self.led_orientation = led_orientation


if __name__ == '__main__':
    ill = Illuminator()
    for k, v in ill():
        print(k, v)
