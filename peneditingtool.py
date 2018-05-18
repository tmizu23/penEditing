# -*- coding: utf-8 -*-

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import *
import math
import numpy as np

class PenEditingTool(QgsMapTool):

    def __init__(self, canvas,iface):
        QgsMapTool.__init__(self, canvas)
        self.canvas = canvas
        self.iface = iface
        self.state = "free" #free,drawing,editing
        self.drawingstate = "plotting" #plotting,dragging
        self.selected = False
        self.rb = None
        self.startmarker = QgsVertexMarker(self.canvas)
        self.startmarker.setIconType(QgsVertexMarker.ICON_BOX)
        self.startmarker.hide()
        self.featid = None
        self.alt = False
        self.ctrl = False
        #our own fancy cursor
        self.cursor = QCursor(QPixmap(["16 16 3 1",
                                       "      c None",
                                       ".     c #FF0000",
                                       "+     c #faed55",
                                       "                ",
                                       "       +.+      ",
                                       "      ++.++     ",
                                       "     +.....+    ",
                                       "    +.  .  .+   ",
                                       "   +.   .   .+  ",
                                       "  +.    .    .+ ",
                                       " ++.    .    .++",
                                       " ... ...+... ...",
                                       " ++.    .    .++",
                                       "  +.    .    .+ ",
                                       "   +.   .   .+  ",
                                       "   ++.  .  .+   ",
                                       "    ++.....+    ",
                                       "      ++.++     ",
                                       "       +.+      "]))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Alt:
            self.alt = True
        elif event.key() == Qt.Key_Control:
            self.ctrl = True
        elif event.key() == Qt.Key_Return:
            if self.state=="drawing":
                self.finish_drawing()
            elif self.state=="editing":
                self.finish_editing()


    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Alt:
            self.alt = False
        elif event.key() == Qt.Key_Control:
            self.ctrl = False

    # 補間
    def interpolate(self, geom):
        poly = geom.asPolyline()
        x_interp = []
        y_interp = []
        for p0, p1 in zip(poly[:-1], poly[1:]):
            x_interp.extend(np.linspace(p0[0], p1[0], 20))
            y_interp.extend(np.linspace(p0[1], p1[1], 20))
        poly_interp = [QgsPoint(x, y) for x, y in zip(x_interp, y_interp)]
        geom_interp = QgsGeometry().fromPolyline(poly_interp)
        return geom_interp

    #移動平均でスムージング
    def smoothing(self,geom):
        poly = geom.asPolyline()
        poly=np.reshape(poly,(-1,2)).T
        num = 8
        b = np.ones(num) / float(num)
        x_pad = np.pad(poly[0], (num-1, 0), 'edge')
        y_pad = np.pad(poly[1], (num-1, 0), 'edge')
        x_smooth = np.convolve(x_pad, b, mode='valid')
        y_smooth = np.convolve(y_pad, b, mode='valid')
        poly_smooth = [QgsPoint(x, y) for x,y in zip(x_smooth,y_smooth)]
        geom_smooth = QgsGeometry().fromPolyline(poly_smooth)
        return geom_smooth

    def createFeature(self, geom, feat):
        layer = self.canvas.currentLayer()
        provider = layer.dataProvider()
        #toleranceで指定したピクセル数以内のゆらぎをシンプルにする
        #simplifyの引数の単位は長さなので変換する
        # tolerance = self.get_tolerance()
        # d = self.canvas.mapUnitsPerPixel()
        # geom = geom.simplify(tolerance*d)

        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            s.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))

        # validate geometry
        f = QgsFeature()
        f.setGeometry(geom)

        # add attribute fields to feature
        fields = layer.pendingFields()
        f.initAttributes(fields.count())

        if feat is None:
            for i in range(fields.count()):
                if provider.defaultValue(i):
                    f.setAttribute(i, provider.defaultValue(i))
        else:
            for i in range(fields.count()):
                    f.setAttribute(i, feat.attributes()[i])

        layer.beginEditCommand("Feature added")

        settings = QSettings()
        disable_attributes = settings.value("/qgis/digitizing/disable_enter_attribute_values_dialog", False, type=bool)
        if disable_attributes or feat is not None:
            layer.addFeature(f)
            layer.endEditCommand()
        else:
            dlg = self.iface.getFeatureForm(layer, f)
            if dlg.exec_():
                layer.endEditCommand()
            else:
                layer.destroyEditCommand()


    def editFeature(self, geom, f, hidedlg):
        layer = self.canvas.currentLayer()
        # tolerance = self.get_tolerance()
        # d = self.canvas.mapUnitsPerPixel()
        # geom = geom.simplify(tolerance*d)
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            geom.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))
        layer.beginEditCommand("Feature edited")
        settings = QSettings()
        disable_attributes = settings.value("/qgis/digitizing/disable_enter_attribute_values_dialog", False, type=bool)
        if disable_attributes or hidedlg:
            layer.changeGeometry(f.id(), geom)
            layer.endEditCommand()
        else:
            dlg = self.iface.getFeatureForm(layer, f)
            if dlg.exec_():
                layer.changeGeometry(f.id(), geom)
                layer.endEditCommand()
            else:
                layer.destroyEditCommand()


    def getFeatureById(self,layer,featid):
        features = [f for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(featid))]
        if len(features) != 1:
            return None
        else:
            return features[0]

    def closestPointOfGeometry(self,point,geom):
        #フィーチャとの距離が近いかどうかを確認
        near = False
        (dist, minDistPoint, afterVertex)=geom.closestSegmentWithContext(point)
        d = self.canvas.mapUnitsPerPixel() * 10
        if math.sqrt(dist) < d:
            near = True
        return near,minDistPoint,afterVertex

    def getNearFeature(self, layer,point):
        d = self.canvas.mapUnitsPerPixel() * 4
        rect = QgsRectangle((point.x() - d), (point.y() - d), (point.x() + d), (point.y() + d))
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            rectGeom = QgsGeometry.fromRect(rect)
            rectGeom.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))
            rect = rectGeom.boundingBox()
        request = QgsFeatureRequest()
        request.setLimit(1)
        request.setFilterRect(rect)
        f = [feat for feat in layer.getFeatures(request)]  # only one because of setlimit(1)
        if len(f)==0:
            return None
        else:
            return f[0]

    def check_selection(self,layer):
        featid_list = layer.selectedFeaturesIds()
        if len(featid_list) > 0:
            return True,featid_list
        else:
            return False,featid_list

    def selectNearFeature(self,layer,pnt):
        #近い地物を選択
        layer.removeSelection()
        f = self.getNearFeature(layer,pnt)
        if f is not None:
            featid = f.id()
            layer.select(featid)


    def canvasPressEvent(self, event):
        self.log("press")
        layer = self.canvas.currentLayer()
        if not layer:
            return
        button_type = event.button()

        pnt = self.toMapCoordinates(event.pos())
        self.selected, featids = self.check_selection(layer)
        near = False
        if self.state=="free":
            #選択されている地物と交差するポイントを取得
            if self.selected:
                f = self.getFeatureById(layer,[featids[0]])
                geom = QgsGeometry(f.geometry())
                self.check_crs()
                if self.layerCRSSrsid != self.projectCRSSrsid:
                    geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
                near,minDistPoint,afterVertex = self.closestPointOfGeometry(pnt,geom)
        elif self.state=="drawing" or self.state=="editing":
            #作成中のrbのラインに近いか
            geom = self.rb.asGeometry()
            near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt,geom)

        if button_type==2:
            #新規の確定
            if self.state=="drawing":
                self.finish_drawing()
            #編集の確定
            elif self.state=="editing":
                self.finish_editing()
            # ctrlを押しながらで属性ポップアップ
            elif self.state == "free" and self.ctrl and  near:
                layer.beginEditCommand("edit attribute")
                dlg = self.iface.getFeatureForm(layer, f)
                if dlg.exec_():
                    layer.endEditCommand()
                else:
                    layer.destroyEditCommand()
                self.ctrl = False
                layer.removeSelection()
            # altを押しながらで切断（選択地物）
            elif self.state == "free" and self.alt and near:
                polyline = geom.asPolyline()
                line1 = polyline[0:afterVertex]
                line1.append(minDistPoint)
                line2 = polyline[afterVertex:]
                line2.insert(0, minDistPoint)
                self.createFeature(QgsGeometry.fromPolyline(line2), f)
                self.editFeature(QgsGeometry.fromPolyline(line1), f, True)
                self.canvas.currentLayer().removeSelection()
            # 近い地物を選択
            elif self.state=="free":
                self.selectNearFeature(layer, pnt)


        elif button_type == 1:
            # 編集開始（選択地物）
            #　rbに変換して、編集処理。geomは一旦削除
            if self.state=="free" and near:
                layer.removeSelection()
                geom = self.interpolate(geom)
                near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt, geom)
                polyline = geom.asPolyline()
                del polyline[afterVertex:]
                self.set_rb()
                self.setRubberBandPoints(polyline, self.rb)
                self.rb.addPoint(pnt)
                self.state = "editing"
                self.drawingstate = "dragging"
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices() - 1
                self.featid = featids[0]
            # 新規開始
            elif self.state == "free":
                self.set_rb()
                self.rb.addPoint(pnt) #最初のポイントは同じ点が2つ追加される仕様？
                self.startmarker.setCenter(pnt)
                self.startmarker.show()
                self.state="drawing"
                self.drawingstate = "dragging"
                self.drawingpoints =[]
                self.drawingidx = 0
            # 編集開始（未確定地物）
            elif (self.state == "drawing" or self.state == "editing") and near:
                rbgeom = self.rb.asGeometry()
                rbgeom = self.interpolate(rbgeom)
                near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt, rbgeom)
                rbline = rbgeom.asPolyline()
                del rbline[afterVertex:]
                self.setRubberBandPoints(rbline, self.rb)
                self.rb.addPoint(pnt)
                self.drawingstate = "dragging"
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices() - 1
            # プロット
            elif (self.state == "drawing" or self.state == "editing"):
                pnt = self.toMapCoordinates(event.pos())
                self.rb.addPoint(pnt)
                self.drawingstate = "dragging"
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices()-1

    def canvasMoveEvent(self, event):
        layer = self.canvas.currentLayer()
        if not layer:
            return
        pnt = self.toMapCoordinates(event.pos())
        #作成中、編集中
        if (self.state=="drawing" or self.state == "editing") and self.drawingstate=="dragging":
            self.rb.addPoint(pnt)
            self.drawingpoints.append(pnt)

    def canvasReleaseEvent(self, event):
        # ドロー終了
        if (self.state == "drawing" or self.state == "editing") and self.drawingstate == "dragging":
            #スムーズ処理してrbを付け替える
            if len(self.drawingpoints) > 0:
                rbgeom = self.rb.asGeometry()
                rbline = rbgeom.asPolyline()
                #前の部分の一部にドロー部分加えてスムーズ処理
                if self.drawingidx >= 8:
                    points = rbline[self.drawingidx - 7:self.drawingidx + 1] + self.drawingpoints
                else:
                    points = self.drawingpoints
                geom = QgsGeometry().fromPolyline(points)
                geom = self.smoothing(geom)
                drawline = geom.asPolyline()
                if self.drawingidx >= 8:
                    rbline[self.drawingidx - 7:] = drawline
                else:
                    rbline[self.drawingidx + 1:] = drawline
                geom = QgsGeometry().fromPolyline(rbline)
                tolerance = self.get_tolerance()
                d = self.canvas.mapUnitsPerPixel()
                geom = geom.simplify(tolerance * d)
                rbline = geom.asPolyline()
                self.setRubberBandPoints(rbline,self.rb)
            self.drawingstate = "plotting"

    def setRubberBandPoints(self, points, rb):
        # 最後に更新
        rb.reset(QGis.Line)
        for point in points:
            update = point is points[-1]
            rb.addPoint(point, update)

    def finish_editing(self):
        layer = self.canvas.currentLayer()
        if self.rb.numberOfVertices() > 1:
            geom = self.rb.asGeometry()
            f = self.getFeatureById(layer,[self.featid])
            self.editFeature(geom, f,False)
        # reset rubberband and refresh the canvas
        self.state = "free"
        self.rb.reset()
        self.rb = None
        self.startmarker.hide()
        self.canvas.refresh()

    def finish_drawing(self):
        if self.rb.numberOfVertices() > 1:
            geom = self.rb.asGeometry()
            self.createFeature(geom, None)

        # reset rubberband and refresh the canvas
        self.state = "free"
        self.rb.reset()
        self.rb = None
        self.startmarker.hide()
        self.canvas.refresh()

    def set_rb(self):
        self.rb = QgsRubberBand(self.canvas)
        self.rb.setColor(QColor(255, 0, 0, 150))
        self.rb.setWidth(2)

    def check_crs(self):
        layer = self.canvas.currentLayer()
        renderer = self.canvas.mapSettings()
        self.layerCRSSrsid = layer.crs().srsid()
        self.projectCRSSrsid = renderer.destinationCrs().srsid()

    def get_tolerance(self):
        settings = QSettings()
        tolerance = settings.value("/penEdit/tolerance",
                                       0.000, type=float)
        return tolerance

    def showSettingsWarning(self):
        pass

    def activate(self):
        self.canvas.setCursor(self.cursor)
        self.alt = False
        self.ctrl = False

    def deactivate(self):
        pass

    def isZoomTool(self):
        return False

    def isTransient(self):
        return False

    def isEditTool(self):
        return True

    def log(self,msg):
        QgsMessageLog.logMessage(msg, 'MyPlugin',QgsMessageLog.INFO)

