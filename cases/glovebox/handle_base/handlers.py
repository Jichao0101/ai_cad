# -*- coding: utf-8 -*-
"""Shared container build helpers."""


def build_mechanical_tool(self, r, d, c):
    settings = self.app.SettingControllers.Item('CATMmuPartInfrastructureSettingCtrl')
    original = settings.HybridDesignMode
    try:
        settings.HybridDesignMode = False
        obj = self.part.Bodies.Add()
    finally:
        settings.HybridDesignMode = original
    return self.own(obj)


def build_gsm_tool(self, r, d, c):
    obj = c.HybridBodies.Add()
    return self.own(obj)
