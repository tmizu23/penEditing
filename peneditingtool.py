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
        self.selected = False
        self.rb = None
        self.startmarker = None
        self.startpoint = None
        self.lastpoint = None
        self.featid = None
        #self.ignoreclick = False
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
        startpnt = self.toMapCoordinates(self.layer,startpnt)
        lastpnt = self.toMapCoordinates(self.layer, lastpnt)
        _, near_startpnt, startidx = self.closestPointOfFeature(startpnt,featid)
        near, near_lastpnt, lastidx = self.closestPointOfFeature(lastpnt,featid)
        startpnt_is_nearest_to_edited_start = self.distance(near_startpnt, editedline[startidx-1]) < self.distance(near_lastpnt,
                                                                                                          editedline[startidx-1])

        #半分以上から始まり始点で終わる場合
        is_closeline_forward = (startidx >= len(editedline)/2 and lastidx == 1 and len(editedline)>2)
        is_closeline_reward = (startidx <= len(editedline)/2 and lastidx == len(editedline) - 1 and len(editedline)>2)

        # 部分の修正なので終点も修正オブジェクトの近くで終わっている。ただし、ポリゴンを閉じるような修正はのぞく
        if near and not is_closeline_forward and not is_closeline_reward :
            # 始点、終点をnearpntに付け替え
            del drawline[0]
            drawline.insert(0, near_startpnt)
            del drawline[-1]
            drawline.insert(-1, near_lastpnt)
            #drawlineとeditedlineの向きが順方向の場合.
            #startidxが最終vertex上でlastidxが最終vertexを超える場合.2頂点内の修正で、startpntの方がeditedlineの最初のポイントに近い場合
            if (lastidx >= startidx and len(editedline)>2) or (startidx==lastidx and startpnt_is_nearest_to_edited_start):
                drawline.reverse()
                del editedline[startidx:lastidx]
                for (x0, y0) in drawline:
                    editedline.insert(startidx, (x0, y0))

            #drawlineとeditedlineの向きが逆の場合.上記以外
            else:
                del editedline[lastidx:startidx]
                for (x0, y0) in drawline:
                    editedline.insert(lastidx, (x0, y0))
        # 終点は離れている.もしくはポリゴンを閉じるような場合
        else:
            # 始点をnearpntに付け替え
            del drawline[0]
            drawline.insert(0, near_startpnt)
            #２点だけの場合、startpntの方がeditedlineの最初のポイントに近い場合。
            is_forward = False
            if len(editedline)==2:
                if startpnt_is_nearest_to_edited_start:
                    is_forward = True
            else:
                #半分以上から始まる場合
                if (startidx >=len(editedline)/2):
                    is_forward = True
            if is_forward:
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

        #toleranceで指定したピクセル数以内のゆらぎをシンプルにする
        #simplifyの引数の単位は長さなので変換する
        tolerance = self.get_tolerance()
        d = self.canvas.mapUnitsPerPixel()
        s = geom.simplify(tolerance*d)

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
        d = self.canvas.mapUnitsPerPixel()
        s = geom.simplify(tolerance*d)
        self.layer.beginEditCommand("Feature edited")
        self.layer.changeGeometry(fid, s)
        self.layer.endEditCommand()

    def getFeaturesById(self,featid):
        features = [f for f in self.layer.getFeatures(QgsFeatureRequest().setFilterFids(featid))]
        return features

    def closestPointOfFeature(self,point,featid):
        #フィーチャとの距離が近いかどうかを確認
        near = False
        features=self.getFeaturesById(featid)
        if len(features) == 1 and self.layer.featureCount() > 0:
            pnt = self.toLayerCoordinates(self.layer, point)
            (dist, minDistPoint, afterVertex)=features[0].geometry().closestSegmentWithContext(pnt)
            d = self.canvas.mapUnitsPerPixel() * 10
            #self.log("dist:{},d:{},{},{},{}".format(math.sqrt(dist),d,featid,point,pnt))
            if math.sqrt(dist) < d:
                near = True
            return near,minDistPoint,afterVertex
        else:
            return near,None,None

    def canvasDoubleClickEvent(self,event):
        #近い地物を選択

        self.canvas.currentLayer().removeSelection()
        point = self.toLayerCoordinates(self.layer, event.pos())
        d = self.canvas.mapUnitsPerPixel() * 4
        request = QgsFeatureRequest()
        request.setLimit(1)
        request.setFilterRect(QgsRectangle((point.x() - d), (point.y() - d), (point.x() + d), (point.y() + d)))
        f = [feat for feat in self.layer.getFeatures(request)]  # only one because of setlimit(1)
        if len(f) == 1:
            featid = f[0].id()
            self.layer.select(featid)
            if self.selected:
                # 頂点に近い場合は、頂点を削除
                geom = QgsGeometry(f[0].geometry())
                dist,atVertex = geom.closestVertexWithContext(point)
                d = self.canvas.mapUnitsPerPixel() * 4
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
        # if self.ignoreclick:
        #     # ignore secondary canvasPressEvents if already drag-drawing
        #     # NOTE: canvasReleaseEvent will still occur (ensures rb is deleted)
        #     # click on multi-button input device will halt drag-drawing
        #     return
        self.layer = self.canvas.currentLayer()
        if not self.layer:
            return
        button_type = event.button()

        pnt = self.getPoint_with_Highlight(event, self.layer)
        self.selected, featid = self.check_selection()
        near,minDistPoint,afterVertex = self.closestPointOfFeature(pnt,featid)
        #self.log("{}".format(minDistPoint))
        if button_type==2 and near:
            f = self.getFeaturesById(featid)
            geom = QgsGeometry(f[0].geometry())
            polyline=geom.asPolyline()
            line1=polyline[0:afterVertex]
            line1.append(minDistPoint)
            line2 = polyline[afterVertex:]
            line2.insert(0,minDistPoint)
            #self.log("{}".format(line2))
            self.editFeature(QgsGeometry.fromPolyline(line1),f[0].id())
            self.createFeature(QgsGeometry.fromPolyline(line2))
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
                self.check_crs()
                if self.layerCRSSrsid != self.projectCRSSrsid:
                    geom.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))
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


    # def setIgnoreClick(self, ignore):
    #     """Used to keep the tool from registering clicks during modal dialogs"""
    #     self.ignoreclick = ignore

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

