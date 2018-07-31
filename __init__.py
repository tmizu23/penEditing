# -*- coding: utf-8 -*-

def name():
    return "Pen editing"


def description():
    return "Pen line/polygon editing"


def version():
    return "Version 0.6.6"


def icon():
    return "icon.png"


def qgisMinimumVersion():
    return "2.18"

def author():
    return "Takayuki Mizutani"

def email():
    return "mizutani@ecoris.co.jp"

def classFactory(iface):
  from penediting import PenEditing
  return PenEditing(iface)

