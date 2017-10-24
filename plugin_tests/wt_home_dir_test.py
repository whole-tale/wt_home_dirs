#!/usr/bin/env python
# -*- coding: utf-8 -*-

from tests import base


def setUpModule():
    base.enabledPlugins.append('wt_sils')
    base.startServer()

def tearDownModule():
    base.stopServer()


class IntegrationTestCase(base.TestCase):
    def setUp(self):
        base.TestCase.setUp(self)

    def tearDown(self):
        base.TestCase.tearDown(self)
