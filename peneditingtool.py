# -*- coding: utf-8 -*-

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import *
import math

class PenEditingTool(QgsMapTool):

    def __init__(self, canvas,iface):
        QgsMapTool.__init__(self, canvas)
        self.canvas = canvas
        self.iface = iface
        self.snapping = True
        self.state = "free" #free,drawing,editing
        self.rb = None
        self.startmarker = None
        self.startpoint = None
        self.lastpoint = None
        self.featid = None
        self.ignoreclick = False
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
        #QgsMessageLog.logMessage("start pen plugin", 'MyPlugin', QgsMessageLog.INFO)

    def getPoint_with_Highlight(self,event,layer):
        #マウス位置をプロジェクトの座標系で返す
        #スナップ地点をハイライトする（スナップはしない.閾値は4ピクセル）
        #描画中のスタート地点へのスナップは自分で実装.
        self.snapmarker.hide()
        x = event.pos().x()
        y = event.pos().y()

        startingPoint = QPoint(x, y)
        snapper = QgsMapCanvasSnapper(self.canvas)
        d = self.canvas.mapUnitsPerPixel() * 4
        (retval, result) = snapper.snapToCurrentLayer(startingPoint,QgsSnapper.SnapToVertex,d)
        if result:
            point = result[0].snappedVertex
            self.snapmarker.setCenter(point)
            self.snapmarker.show()
            point = self.toLayerCoordinates(layer,point)
        else:
            point = self.toLayerCoordinates(layer, event.pos())

        pnt = self.toMapCoordinates(layer, point)

        #スタート地点にスナップ。rbは通常のスナップ機能は有効でないため自分で実装

        if self.state=="drawing" or self.state=="editing":
            if (self.startpoint.x()-d <= pnt.x() <= self.startpoint.x()+d) and (self.startpoint.y()-d<=pnt.y() <= self.startpoint.y()+d):
                self.snapmarker.setCenter(self.startpoint)
                self.snapmarker.show()

        point = self.toLayerCoordinates(layer, event.pos())
        pnt = self.toMapCoordinates(layer, point)
        return pnt

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
        editedline = editedgeom.asPolyline()
        featid = self.layer.selectedFeaturesIds()
        _, _, near_startpnt, startidx = self.closestFeature(startpnt,featid)
        near, _, near_lastpnt, lastidx = self.closestFeature(lastpnt,featid)
        startpnt_is_nearest_to_edited_start = self.distance(near_startpnt, editedline[0]) < self.distance(near_lastpnt,
                                                                                                          editedline[0])
        # 終点は近い
        if near:
            # 始点、終点をnearpntに付け替え
            del drawline[0]
            drawline.insert(0, near_startpnt)
            del drawline[-1]
            drawline.insert(-1, near_lastpnt)
            #drawlineとeditedlineの向きが順方向の場合.
            #startidxが最終vertex上でlastidxが最終vertexを超える場合.editedlineの頂点が2つで、startpntの方がeditedlineの最初のポイントに近い場合
            if lastidx > startidx or (lastidx==len(editedline)-1 and len(editedline)>2) or (len(editedline)==2 and startpnt_is_nearest_to_edited_start):
                drawline.reverse()
                del editedline[startidx:lastidx]
                for (x0, y0) in drawline:
                    editedline.insert(startidx, (x0, y0))
            #drawlineとeditedlineの向きが逆の場合.上記以外
            else:
                del editedline[lastidx:startidx]
                for (x0, y0) in drawline:
                    editedline.insert(lastidx, (x0, y0))

        # 終点は離れている
        else:
            # 始点をnearpntに付け替え
            del drawline[0]
            drawline.insert(0, near_startpnt)
            if lastidx > startidx or (lastidx==len(editedline)-1 and len(editedline)>2) or (len(editedline)==2 and startpnt_is_nearest_to_edited_start):
                drawline.reverse()
                del editedline[startidx:]
                for (x0, y0) in drawline:
                    editedline.insert(startidx, (x0, y0))
            else:
                del editedline[:startidx]
                for (x0, y0) in drawline:
                    editedline.insert(0, (x0, y0))

        polyline = [QgsPoint(pair[0], pair[1]) for pair in editedline]
        geom = QgsGeometry.fromPolyline(polyline)
        self.editFeature(geom, f.id())

    def createFeature(self, geom):
        settings = QSettings()
        provider = self.layer.dataProvider()

        self.check_crs()
        # On the Fly reprojection.
        if self.layerCRSSrsid != self.projectCRSSrsid:
            geom.transform(QgsCoordinateTransform(self.projectCRSSrsid,
                                                  self.layerCRSSrsid))
        tolerance = self.get_tolerance()
        s = geom.simplify(tolerance)

        # validate geometry
        f = QgsFeature()
        f.setGeometry(s)

        # add attribute fields to feature
        fields = self.layer.pendingFields()
        f.initAttributes(fields.count())
        for i in range(fields.count()):
            if provider.defaultValue(i):
                f.setAttribute(i, provider.defaultValue(i))

        self.layer.beginEditCommand("Feature added")
        self.layer.addFeature(f)
        self.layer.endEditCommand()


    def editFeature(self, geom, fid):
        tolerance = self.get_tolerance()
        s = geom.simplify(tolerance)
        # validate geometry
        if s.validateGeometry():
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                'Feature not valid',
                "The geometry of the feature you just added isn't valid."
                "Do you want to use it anyway?",
                QMessageBox.Yes, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        self.layer.beginEditCommand("Feature edited")
        self.layer.changeGeometry(fid, s)
        self.layer.endEditCommand()

    def closestFeature(self,pnt,featid):
        #選択されているフィーチャとの距離が近いかどうかを確認
        near = False
        if len(featid) == 1 and self.layer.featureCount() > 0:
            f = self.layer.getFeatures(QgsFeatureRequest().setFilterFids(featid)).next()
            (dist, minDistPoint, afterVertex)=f.geometry().closestSegmentWithContext(pnt)
            d = self.canvas.mapUnitsPerPixel() * 10
            #self.log("dist:{},d:{},{}".format(math.sqrt(dist),d,featid))
            if math.sqrt(dist) < d:
                near = True
            return near,featid,minDistPoint,afterVertex
        else:
            return near,None,None,None

    def canvasDoubleClickEvent(self,event):
        #近い地物を選択
        self.canvas.currentLayer().removeSelection()
        point = self.toLayerCoordinates(self.layer, event.pos())
        d = self.canvas.mapUnitsPerPixel() * 4
        request = QgsFeatureRequest()
        request.setLimit(1)
        request.setFilterRect(QgsRectangle((point.x() - d), (point.y() - d), (point.x() + d), (point.y() + d)))
        f = self.layer.getFeatures(request).next()
        featid = f.id()
        self.layer.select(featid)

        # 頂点に近い場合は、頂点を削除
        geom = QgsGeometry(f.geometry())
        dist,atVertex = geom.closestVertexWithContext(point)
        d = self.canvas.mapUnitsPerPixel() * 4
        if math.sqrt(dist) < d:
            geom.deleteVertex(atVertex)
            self.editFeature(geom, featid)


    def canvasPressEvent(self, event):
        if self.ignoreclick:
            # ignore secondary canvasPressEvents if already drag-drawing
            # NOTE: canvasReleaseEvent will still occur (ensures rb is deleted)
            # click on multi-button input device will halt drag-drawing
            return
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return

        # start editing
        #近いかどうか
        pnt = self.getPoint_with_Highlight(event, self.layer)
        featid = self.layer.selectedFeaturesIds()
        near, featid,_,_ = self.closestFeature(pnt,featid)
        if near:
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
        pnt = self.getPoint_with_Highlight(event, self.layer)
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
                self.check_crs()
                if self.layerCRSSrsid != self.projectCRSSrsid:
                    rbgeom.transform(QgsCoordinateTransform(self.projectCRSSrsid,self.layerCRSSrsid))
                feature=self.layer.getFeatures(QgsFeatureRequest().setFilterFids(self.featid)).next()
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
                self.createFeature(geom)

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
        if self.layer.crs().projectionAcronym() == "longlat":
            tolerance = 0.000
        else:
            tolerance = settings.value("/penEdit/tolerance",
                                       0.000, type=float)
        return tolerance


    def setIgnoreClick(self, ignore):
        """Used to keep the tool from registering clicks during modal dialogs"""
        self.ignoreclick = ignore

    def showSettingsWarning(self):
        pass

    def activate(self):
        self.canvas.setCursor(self.cursor)
        self.layer = self.canvas.currentLayer()
        self.check_crs()
        self.snapmarker = QgsVertexMarker(self.canvas)
        self.snapmarker.setIconType(QgsVertexMarker.ICON_BOX)
        self.snapmarker.setColor(QColor(255,165,0))
        self.snapmarker.setPenWidth(3)
        self.snapmarker.setIconSize(10)
        self.snapmarker.hide()
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

