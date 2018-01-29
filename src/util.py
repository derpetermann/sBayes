#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, \
    unicode_literals

from math import sqrt, atan2

import numpy as np


def compute_distance(a, b):
    """
        This function computes the Euclidean distance between two points a and b
        :In
          - A: x and y coordinates of the point a, in a metric CRS
          - B: x and y coordinates of the point b, in a metric CRS.
        :Out
          - dist: the Euclidean distance from a to b
        """
    a = np.asarray(a)
    b = np.asarray(b)
    ab = b-a
    dist = sqrt(ab[0]**2 + ab[1]**2)

    return dist


def compute_direction(a, b):
    """
        This function computes the direction between two points a and b in clockwise direction
        north = 0 , east = pi/2, south = pi, west = 3pi/2
        :In
          - A: x and y coordinates of the point a, in a metric CRS
          - B: x and y coordinates of the point b, in a metric CRS.
        :Out
          - dir_rad: the direction from A to B in radians
        """
    a = np.asarray(a)
    b = np.asarray(b)
    ba = b - a
    return (np.pi/2 - atan2(ba[1], ba[0])) % (2*np.pi)