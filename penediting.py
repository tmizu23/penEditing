# -*- coding: utf-8 -*-

# Import the PyQt and the QGIS libraries
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import *

#Import own classes and tools
from peneditingtool import PenEditingTool

# initialize Qt resources from file resources.py
import resources


class PenEditing:

    def __init__(self, iface):
      # Save reference to the QGIS interface
        self.iface = iface
        self.canvas = self.iface.mapCanvas()
        self.active = False

    def initGui(self):
        settings = QSettings()
        # Create action
        self.pen_edit = \
            QAction(QIcon(":/plugins/penEditing/icon.png"),
                    "Pen editing", self.iface.mainWindow())
        self.pen_edit.setEnabled(False)
        self.pen_edit.setCheckable(True)
        # Add toolbar button and menu item
        self.iface.digitizeToolBar().addAction(self.pen_edit)
        self.iface.editMenu().addAction(self.pen_edit)

        self.spinBox = QDoubleSpinBox(self.iface.mainWindow())
        self.spinBox.setDecimals(3)
        self.spinBox.setMinimum(0.000)
        self.spinBox.setMaximum(5.000)
        self.spinBox.setSingleStep(0.100)
        toleranceval = \
            settings.value("/penEdit/tolerance", 0.000, type=float)
        if not toleranceval:
            settings.setValue("/penEdit/tolerance", 0.000)
        self.spinBox.setValue(toleranceval)
        self.spinBoxAction = \
            self.iface.digitizeToolBar().addWidget(self.spinBox)
        self.spinBox.setToolTip("Tolerance. Level of simplification.")
        self.spinBoxAction.setEnabled(False)

        # Connect to signals for button behaviour
        self.pen_edit.activated.connect(self.penediting)
        self.iface.currentLayerChanged['QgsMapLayer*'].connect(self.toggle)
        self.canvas.mapToolSet['QgsMapTool*'].connect(self.deactivate)
        self.spinBox.valueChanged[float].connect(self.tolerancesettings)

        # Get the tool
        self.tool = PenEditingTool(self.canvas,self.iface)

    def tolerancesettings(self):
        settings = QSettings()
        settings.setValue("/penEdit/tolerance", self.spinBox.value())

    def penediting(self):
        self.canvas.setMapTool(self.tool)
        self.pen_edit.setChecked(True)
        self.active = True

    def toggle(self):
        mc = self.canvas
        layer = mc.currentLayer()
        if layer is None:
            return

        #Decide whether the plugin button/menu is enabled or disabled
        if (layer.isEditable() and (layer.geometryType() == QGis.Line or layer.geometryType() == QGis.Polygon)):
            self.pen_edit.setEnabled(True)
            self.spinBoxAction.setEnabled(True)
            try:  # remove any existing connection first
                layer.editingStopped.disconnect(self.toggle)
            except TypeError:  # missing connection
                pass
            layer.editingStopped.connect(self.toggle)
            try:
                layer.editingStarted.disconnect(self.toggle)
            except TypeError:  # missing connection
                pass
        else:
            self.pen_edit.setEnabled(False)
            self.spinBoxAction.setEnabled(False)
            if (layer.type() == QgsMapLayer.VectorLayer and
                    (layer.geometryType() == QGis.Line or
                     layer.geometryType() == QGis.Polygon)):
                try:  # remove any existing connection first
                    layer.editingStarted.disconnect(self.toggle)
                except TypeError:  # missing connection
                    pass
                layer.editingStarted.connect(self.toggle)
                try:
                    layer.editingStopped.disconnect(self.toggle)
                except TypeError:  # missing connection
                    pass


    def deactivate(self):
        self.pen_edit.setChecked(False)
        self.active = False

    def unload(self):
        self.iface.digitizeToolBar().removeAction(self.pen_edit)
        self.iface.digitizeToolBar().removeAction(self.spinBoxAction)