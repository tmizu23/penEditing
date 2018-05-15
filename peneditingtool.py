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
        self.selected = False
        self.rb = None
        self.startmarker = None
        self.startpoint = None
        self.lastpoint = None
        self.featid = None
        self.layer = False
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

    def distance(self,p1, p2):
        dx = p1[0] - p2[0]
        dy = p1[1] - p2[1]
        return math.sqrt(dx * dx + dy * dy)

    def modify_obj(self,rbgeom,f):
        drawgeom = QgsGeometry(rbgeom)
        drawline = drawgeom.asPolyline()

        startpnt = drawline[0]
        lastpnt = drawline[-1]

        editedgeom = QgsGeometry(f.geometry())
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            editedgeom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
        editedline = editedgeom.asPolyline()
        featid = [f.id()]
        _, near_startpnt, startidx = self.closestPointOfFeature(startpnt,featid)
        near, near_lastpnt, lastidx = self.closestPointOfFeature(lastpnt,featid)
        startpnt_is_nearest_to_edited_start = self.distance(near_startpnt, editedline[startidx-1]) < self.distance(near_lastpnt,
                                                                                                          editedline[startidx-1])

        #半分以上から始まり始点で終わる場合
        is_closeline_forward = (startidx >= len(editedline)/2 and lastidx == 1 and len(editedline)>2)
        is_closeline_reward = (startidx <= len(editedline)/2 and lastidx == len(editedline) - 1 and len(editedline)>2)

        # 部分の修正なので終点も修正オブジェクトの近くで終わっている。ただし、ポリゴンを閉じるような修正はのぞく
        if near and not is_closeline_forward and not is_closeline_reward :
            #drawlineとeditedlineの向きが順方向の場合.
            #startidxが最終vertex上でlastidxが最終vertexを超える場合.2頂点内の修正で、startpntの方がeditedlineの最初のポイントに近い場合
            if (lastidx >= startidx and len(editedline)>2) or (startidx==lastidx and startpnt_is_nearest_to_edited_start):
                geom = QgsGeometry.fromPolyline(editedline[startidx-1:startidx]+drawline+editedline[lastidx:lastidx+1])
                drawgeom = self.smoothing(geom)
                drawline = drawgeom.asPolyline()
                drawline.reverse()
                del editedline[startidx-1:lastidx+1]
                for (x0, y0) in drawline:
                    editedline.insert(startidx-1, (x0, y0))

            #drawlineとeditedlineの向きが逆の場合.上記以外
            else:
                starttmp=editedline[startidx:startidx+1]
                starttmp.reverse()
                lasttmp = editedline[lastidx-1:lastidx]
                lasttmp.reverse()
                geom = QgsGeometry.fromPolyline(starttmp+drawline+lasttmp)
                drawgeom = self.smoothing(geom)
                drawline = drawgeom.asPolyline()
                del editedline[lastidx-1:startidx+1]
                for (x0, y0) in drawline:
                    editedline.insert(lastidx-1, (x0, y0))
        # 終点は離れている.もしくはポリゴンを閉じるような場合
        else:
            #2点だけの場合、startpntの方がeditedlineの最初のポイントに近い場合。
            is_forward = False
            if len(editedline)==2:
                if startpnt_is_nearest_to_edited_start:
                    is_forward = True
            else:
                #半分以上から始まる場合
                if (startidx >=len(editedline)/2):
                    is_forward = True
            if is_forward:
                geom = QgsGeometry.fromPolyline(editedline[startidx-2:startidx]+drawline)
                drawgeom = self.smoothing(geom)
                drawline = drawgeom.asPolyline()
                drawline.reverse()
                del editedline[startidx-2:]
                for (x0, y0) in drawline:
                    editedline.insert(startidx-2, (x0, y0))
            else:
                tmp=editedline[startidx:startidx+2]
                tmp.reverse()
                geom = QgsGeometry.fromPolyline(tmp+drawline)
                drawgeom = self.smoothing(geom)
                drawline = drawgeom.asPolyline()
                del editedline[:startidx+2]
                for (x0, y0) in drawline:
                    editedline.insert(0, (x0, y0))

        polyline = [QgsPoint(pair[0], pair[1]) for pair in editedline]
        geom = QgsGeometry.fromPolyline(polyline)
        self.editFeature(geom, f.id())

    #移動平均でスムージング
    def smoothing(self,geom):
        poly = geom.asPolyline()
        poly=np.reshape(poly,(-1,2)).T
        num = 10
        b = np.ones(num) / float(num)
        x_pad = np.pad(poly[0], (num-1, 0), 'edge')
        y_pad = np.pad(poly[1], (num-1, 0), 'edge')
        x_smooth = np.convolve(x_pad, b, mode='valid')
        y_smooth = np.convolve(y_pad, b, mode='valid')
        poly_smooth = [QgsPoint(x, y) for x,y in zip(x_smooth,y_smooth)]
        geom_smooth = QgsGeometry.fromPolyline(poly_smooth)
        return geom_smooth

    def createFeature(self, geom, feat):
        provider = self.layer.dataProvider()
        #新規の時はスムージングする。分割の時はしない
        if feat is None:
            geom = self.smoothing(geom)
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
        if disable_attributes:
            self.layer.addFeature(f)
            self.layer.endEditCommand()
        else:
            dlg = self.iface.getFeatureForm(self.layer, f)
            if dlg.exec_():
                self.layer.endEditCommand()
            else:
                self.layer.destroyEditCommand()


    def editFeature(self, geom, fid):
        tolerance = self.get_tolerance()
        d = self.canvas.mapUnitsPerPixel()
        s = geom.simplify(tolerance*d)
        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            s.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))
        self.layer.beginEditCommand("Feature edited")
        self.layer.changeGeometry(fid, s)
        self.layer.endEditCommand()

    def getFeatureById(self,featid):
        features = [f for f in self.layer.getFeatures(QgsFeatureRequest().setFilterFids(featid))]
        if len(features) != 1:
            return None
        else:
            return features[0]

    def closestPointOfFeature(self,point,featid):
        #フィーチャとの距離が近いかどうかを確認
        near = False
        feature=self.getFeatureById(featid)
        if feature is not None and self.layer.featureCount() > 0:
            geom = QgsGeometry(feature.geometry())
            self.check_crs()
            if self.layerCRSSrsid != self.projectCRSSrsid:
                geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
            (dist, minDistPoint, afterVertex)=geom.closestSegmentWithContext(point)
            d = self.canvas.mapUnitsPerPixel() * 10
            if math.sqrt(dist) < d:
                near = True
            return near,minDistPoint,afterVertex
        else:
            return near,None,None

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
        #近い地物を選択
        layer = self.canvas.currentLayer()
        layer.removeSelection()
        point = self.toMapCoordinates(event.pos())
        f = self.getNearFeature(point)
        if f is not None:
            featid = f.id()
            self.layer.select(featid)
            if self.selected:
                # 選択されていて頂点に近い場合は、頂点を削除
                geom = QgsGeometry(f.geometry())
                self.check_crs()
                if self.layerCRSSrsid != self.projectCRSSrsid:
                    geom.transform(QgsCoordinateTransform(self.layerCRSSrsid,self.projectCRSSrsid))
                dist,atVertex = geom.closestVertexWithContext(point)
                d = self.canvas.mapUnitsPerPixel() * 10
                if math.sqrt(dist) < d:
                    geom.deleteVertex(atVertex)
                    self.editFeature(geom, featid)

    def check_selection(self):
        featid_list = self.layer.selectedFeaturesIds()
        if len(featid_list) > 0:
            return True,featid_list
        else:
            return False,featid_list

    def canvasPressEvent(self, event):
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return
        button_type = event.button()

        pnt = self.toMapCoordinates(event.pos())
        self.selected, featid = self.check_selection()
        near,minDistPoint,afterVertex = self.closestPointOfFeature(pnt,featid)
        if button_type==2 and near:
            f = self.getFeatureById(featid)
            geom = QgsGeometry(f.geometry())
            self.check_crs()
            if self.layerCRSSrsid != self.projectCRSSrsid:
                geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
            polyline=geom.asPolyline()
            line1=polyline[0:afterVertex]
            line1.append(minDistPoint)
            line2 = polyline[afterVertex:]
            line2.insert(0,minDistPoint)
            self.editFeature(QgsGeometry.fromPolyline(line1),f.id())
            self.createFeature(QgsGeometry.fromPolyline(line2),f)
            self.canvas.currentLayer().removeSelection()

        # start editing
        #近いかどうか
        elif button_type==1 and near:
            self.featid = featid
            self.set_rb()
            self.rb.addPoint(pnt)
            self.startmarker.setCenter(pnt)
            self.startmarker.show()
            self.startpoint = pnt
            self.lastpoint = pnt
            self.state = "editing"
        # start drawing
        elif self.state == "free":
            self.set_rb()
            self.rb.addPoint(pnt)
            self.startmarker.setCenter(pnt)
            self.startmarker.show()
            self.startpoint = pnt
            self.lastpoint = pnt
            self.state = "drawing"


 
    def canvasMoveEvent(self, event):
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return
        #ポイントに近いポイント
        pnt = self.toMapCoordinates(event.pos())
        #作成中、編集中
        if self.state=="editing" or self.state=="drawing":
            self.lastpoint = pnt
            self.rb.addPoint(pnt)

    def canvasReleaseEvent(self, event):

        # finish editing
        if self.state=="editing":
            if self.rb.numberOfVertices() > 2:
                rbgeom=self.rb.asGeometry()
                #描画ラインを画面の投影からレイヤの投影に変換
                feature = self.getFeatureById(self.featid)
                self.modify_obj(rbgeom,feature)
            else:
                pass
            self.state = "free"
            self.canvas.currentLayer().removeSelection()
            self.featid = None
            self.rb.reset()
            self.rb = None
            self.startmarker.hide()
            self.canvas.refresh()

        # finish drawing
        if self.state == "drawing":
            if self.rb.numberOfVertices() > 2:
                geom = self.rb.asGeometry()
                self.createFeature(geom,None)

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
        self.startmarker = QgsVertexMarker(self.canvas)
        self.startmarker.setIconType(QgsVertexMarker.ICON_X)
        self.startmarker.hide()

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

