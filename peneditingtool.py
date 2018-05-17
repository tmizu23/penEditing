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
        self.state = "free" #free,drawing,ploting
        self.editing = False
        self.selected = False
        self.rb = None
        #self.startmarker = None
        self.startmarker = QgsVertexMarker(self.canvas)
        self.startmarker.setIconType(QgsVertexMarker.ICON_BOX)
        self.startmarker.hide()
        self.featid = None
        self.layer = False
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
            if self.state=="ploting":
                if self.editing:
                    self.finish_editing()
                else:
                    self.finish_drawing()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Alt:
            self.alt = False
        elif event.key() == Qt.Key_Control:
            self.ctrl = False

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
        provider = self.layer.dataProvider()
        #toleranceで指定したピクセル数以内のゆらぎをシンプルにする
        #simplifyの引数の単位は長さなので変換する
        tolerance = self.get_tolerance()
        d = self.canvas.mapUnitsPerPixel()
        s = geom.simplify(tolerance*d)

        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            s.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))

        # validate geometry
        f = QgsFeature()
        f.setGeometry(s)

        # add attribute fields to feature
        fields = self.layer.pendingFields()
        f.initAttributes(fields.count())

        if feat is None:
            for i in range(fields.count()):
                if provider.defaultValue(i):
                    f.setAttribute(i, provider.defaultValue(i))
        else:
            for i in range(fields.count()):
                    f.setAttribute(i, feat.attributes()[i])

        self.layer.beginEditCommand("Feature added")

        settings = QSettings()
        disable_attributes = settings.value("/qgis/digitizing/disable_enter_attribute_values_dialog", False, type=bool)
        if disable_attributes or feat is not None:
            self.layer.addFeature(f)
            self.layer.endEditCommand()
        else:
            dlg = self.iface.getFeatureForm(self.layer, f)
            if dlg.exec_():
                self.layer.endEditCommand()
            else:
                self.layer.destroyEditCommand()


    def editFeature(self, geom, f, hidedlg):

        tolerance = self.get_tolerance()
        d = self.canvas.mapUnitsPerPixel()
        s = geom.simplify(tolerance*d)
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            s.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))
        self.layer.beginEditCommand("Feature edited")
        settings = QSettings()
        disable_attributes = settings.value("/qgis/digitizing/disable_enter_attribute_values_dialog", False, type=bool)
        if disable_attributes or hidedlg:
            self.layer.changeGeometry(f.id(), s)
            self.layer.endEditCommand()
        else:
            dlg = self.iface.getFeatureForm(self.layer, f)
            if dlg.exec_():
                self.layer.changeGeometry(f.id(), s)
                self.layer.endEditCommand()
            else:
                self.layer.destroyEditCommand()


    def getFeatureById(self,featid):
        features = [f for f in self.layer.getFeatures(QgsFeatureRequest().setFilterFids(featid))]
        if len(features) != 1:
            return None
        else:
            return features[0]

    def closestPointOfGeometry(self,point,geom):
        #フィーチャとの距離が近いかどうかを確認
        near = False
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
        (dist, minDistPoint, afterVertex)=geom.closestSegmentWithContext(point)
        d = self.canvas.mapUnitsPerPixel() * 10
        if math.sqrt(dist) < d:
            near = True
        return near,minDistPoint,afterVertex

    def getNearFeature(self, point):
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
        f = [feat for feat in self.layer.getFeatures(request)]  # only one because of setlimit(1)
        if len(f)==0:
            return None
        else:
            return f[0]

    def canvasDoubleClickEvent(self,event):
        self.log("double")
        self.log("{}".format(self.state))
        #クリックイベントで設定されてしまうため戻す
        if self.rb is not None:
            self.state = "free"
            self.rb.reset()
            self.rb = None
            self.startmarker.hide()
            self.canvas.refresh()

        #近い地物を選択
        layer = self.canvas.currentLayer()
        layer.removeSelection()
        point = self.toMapCoordinates(event.pos())
        f = self.getNearFeature(point)
        if f is not None:
            featid = f.id()
            self.layer.select(featid)
            if self.ctrl:
                # ctrlを押しながらダブルクリックで属性ポップアップ
                layer.beginEditCommand("edit attribute")
                dlg = self.iface.getFeatureForm(layer, f)
                if dlg.exec_():
                    layer.endEditCommand()
                else:
                    layer.destroyEditCommand()
                self.ctrl = False
                layer.removeSelection()

    def check_selection(self):
        featid_list = self.layer.selectedFeaturesIds()
        if len(featid_list) > 0:
            return True,featid_list
        else:
            return False,featid_list

    def canvasPressEvent(self, event):
        self.log("press")
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return
        button_type = event.button()

        pnt = self.toMapCoordinates(event.pos())
        self.selected, featids = self.check_selection()
        near = False
        if self.selected:
            f = self.getFeatureById([featids[0]])
            geom = QgsGeometry(f.geometry())
            near,minDistPoint,afterVertex = self.closestPointOfGeometry(pnt,geom)
        elif self.rb is not None:
            #rbのラインに近いか
            geom = self.rb.asGeometry()
            near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt,geom)
        if button_type==2:
            #確定
            if self.state=="ploting":
                if self.editing:
                    self.finish_editing()
                else:
                    self.finish_drawing()
            #切断（選択地物）
            if self.state=="free" and near:
                self.check_crs()
                if self.layerCRSSrsid != self.projectCRSSrsid:
                    geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
                polyline=geom.asPolyline()
                line1=polyline[0:afterVertex]
                line1.append(minDistPoint)
                line2 = polyline[afterVertex:]
                line2.insert(0,minDistPoint)
                self.createFeature(QgsGeometry.fromPolyline(line2), f)
                self.editFeature(QgsGeometry.fromPolyline(line1),f,True)
                self.canvas.currentLayer().removeSelection()
        elif button_type == 1:
            # 編集開始（選択地物）
            #　rbに変換して、編集処理。geomは一旦削除
            if self.state=="free" and near:
                self.layer.removeSelection()
                polyline = geom.asPolyline()
                del polyline[afterVertex:]
                self.set_rb()
                self.setRubberBandPoints(polyline, self.rb)
                self.rb.addPoint(pnt)
                self.state = "drawing"
                self.editing =True
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices() - 1
                self.featid = featids[0]
            # 新規開始
            elif self.state == "free":
                self.set_rb()
                self.rb.addPoint(pnt) #最初のポイントは同じ点が2つ追加される仕様？
                self.startmarker.setCenter(pnt)
                self.startmarker.show()
                self.state = "drawing"
                self.drawingpoints =[]
                self.drawingidx = 0
            # 編集開始（未確定地物）
            elif self.state == "ploting" and near:
                rbgeom = self.rb.asGeometry()
                rbline = rbgeom.asPolyline()
                del rbline[afterVertex:]
                self.setRubberBandPoints(rbline, self.rb)
                self.rb.addPoint(pnt)
                self.state = "drawing"
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices() - 1
            # プロット
            elif self.state == "ploting":
                pnt = self.toMapCoordinates(event.pos())
                self.rb.addPoint(pnt)
                self.state = "drawing"
                self.drawingpoints = []
                self.drawingidx = self.rb.numberOfVertices()-1

    def canvasMoveEvent(self, event):
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return
        pnt = self.toMapCoordinates(event.pos())
        #作成中、編集中
        if self.state=="drawing":
            self.rb.addPoint(pnt)
            self.drawingpoints.append(pnt)

    def canvasReleaseEvent(self, event):
        # ドロー終了
        if self.state == "drawing":
            #スムーズ処理してrbを付け替える
            if len(self.drawingpoints) > 0:
                rbgeom = self.rb.asGeometry()
                rbline = rbgeom.asPolyline()
                #前の部分の一部にドロー部分加えてスムーズ処理
                if self.ctrl and self.drawingidx >= 8:
                    points = rbline[self.drawingidx - 7:self.drawingidx + 1] + self.drawingpoints
                else:
                    points = self.drawingpoints
                #self.log("{}".format(points))
                geom = QgsGeometry().fromPolyline(points)
                geom = self.smoothing(geom)
                drawline = geom.asPolyline()
                if self.ctrl and self.drawingidx >= 8:
                    rbline[self.drawingidx - 7:] = drawline
                else:
                    rbline[self.drawingidx + 1:] = drawline
                self.setRubberBandPoints(rbline,self.rb)
            self.state = "ploting"

    def setRubberBandPoints(self, points, rb):
        # 最後に更新
        rb.reset(QGis.Line)
        for point in points:
            update = point is points[-1]
            rb.addPoint(point, update)

    def finish_editing(self):
        if self.rb.numberOfVertices() > 1:
            geom = self.rb.asGeometry()
            f = self.getFeatureById([self.featid])
            self.editFeature(geom, f,False)
        # reset rubberband and refresh the canvas
        self.editing = False
        self.state = "free"
        self.rb.reset()
        self.rb = None
        self.startmarker.hide()
        self.canvas.refresh()

    def finish_drawing(self):
        #ダブルクリックのときも、一旦、シングルクリックの処理が実行され
        # stateがdrawingになっているので、vertex_Nで処理を実行しないようにする
        # plotingの時は、2点でもラインを引きたい
        if self.state == "ploting":
            vertex_N = 1
        else:
            vertex_N = 2
        if self.rb.numberOfVertices() > vertex_N:
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
        renderer = self.canvas.mapSettings()
        self.layerCRSSrsid = self.layer.crs().srsid()
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
        self.layer = self.canvas.currentLayer()
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

