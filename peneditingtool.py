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
        self.state = "free" #free,dragging,plotting,editing
        self.rb = None
        self.edit_rb = None
        self.modify = False
        self.snapping = True
        self.snapavoidbool = True
        self.startmarker = QgsVertexMarker(self.canvas)
        self.startmarker.setIconType(QgsVertexMarker.ICON_BOX)
        self.startmarker.hide()
        self.startpoint = None
        self.snapmarker = QgsVertexMarker(self.canvas)
        self.snapmarker.setIconType(QgsVertexMarker.ICON_BOX)
        self.snapmarker.setColor(QColor(0, 0, 255))
        self.snapmarker.setPenWidth(2)
        self.snapmarker.setIconSize(10)
        self.snapmarker.hide()
        self.featid = None
        self.alt = False
        self.drawingline = []

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Alt:
            self.alt = True
        # elif event.key() == Qt.Key_Return:
        #     if self.state=="drawing":
        #         self.finish_drawing()
        #     elif self.state=="editing":
        #         self.finish_editing()


    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Alt:
            self.alt = False


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
    def smoothing(self,polyline):
        poly=np.reshape(polyline,(-1,2)).T
        num = 8
        b = np.ones(num) / float(num)
        x_pad = np.pad(poly[0], (num-1, 0), 'edge')
        y_pad = np.pad(poly[1], (num-1, 0), 'edge')
        x_smooth = np.convolve(x_pad, b, mode='valid')
        y_smooth = np.convolve(y_pad, b, mode='valid')
        poly_smooth = [QgsPoint(x, y) for x,y in zip(x_smooth,y_smooth)]
        return poly_smooth

    def distance(self,p1, p2):
        dx = p1[0] - p2[0]
        dy = p1[1] - p2[1]
        return math.sqrt(dx * dx + dy * dy)

    def modify_obj(self, rbgeom, editedgeom):
        drawgeom = QgsGeometry(rbgeom)
        drawline = drawgeom.asPolyline()

        startpnt = drawline[0]
        lastpnt = drawline[-1]
        #プロットした直線ともスムーズ処理するために一旦補間処理する
        editedgeom = self.interpolate(editedgeom)
        editedline = editedgeom.asPolyline()
        _, near_startpnt, startidx = self.closestPointOfGeometry(startpnt, editedgeom)
        near, near_lastpnt, lastidx = self.closestPointOfGeometry(lastpnt, editedgeom)
        startpnt_is_nearest_to_edited_start = self.distance(near_startpnt, editedline[startidx - 1]) < self.distance(
            near_lastpnt,
            editedline[startidx - 1])

        # 半分以上から始まり始点で終わる場合
        is_closeline_forward = (startidx >= len(editedline) / 2 and lastidx == 1 and len(editedline) > 2)
        is_closeline_reward = (
        startidx <= len(editedline) / 2 and lastidx == len(editedline) - 1 and len(editedline) > 2)

        # 部分の修正なので終点も修正オブジェクトの近くで終わっている。ただし、ポリゴンを閉じるような修正はのぞく
        if near and not is_closeline_forward and not is_closeline_reward:
            # drawlineとeditedlineの向きが順方向の場合.
            # startidxが最終vertex上でlastidxが最終vertexを超える場合.2頂点内の修正で、startpntの方がeditedlineの最初のポイントに近い場合
            if (lastidx >= startidx and len(editedline) > 2) or (
                    startidx == lastidx and startpnt_is_nearest_to_edited_start):
                polyline = editedline[startidx - 8:startidx] + drawline + editedline[lastidx:lastidx + 8]
                editedline[startidx - 8:lastidx + 8] = self.smoothing(polyline)

            # drawlineとeditedlineの向きが逆の場合.上記以外
            else:
                starttmp = editedline[startidx:startidx + 8]
                lasttmp = editedline[lastidx - 8:lastidx]
                drawline.reverse()
                polyline = lasttmp + drawline + starttmp
                editedline[lastidx - 8:startidx + 8]= self.smoothing(polyline)

        # 終点は離れている.もしくはポリゴンを閉じるような場合
        else:
            if startidx <= lastidx or startidx >= len(editedline)/2:
                drawline = drawgeom.asPolyline()
                polyline = editedline[startidx - 8:startidx] + drawline
                editedline[startidx - 8:] = self.smoothing(polyline)
            else:
                drawline = drawgeom.asPolyline()
                drawline.reverse()
                polyline = drawline + editedline[startidx+1:startidx+9]
                editedline[:startidx +9:] = self.smoothing(polyline)

        geom = QgsGeometry().fromPolyline(editedline)
        tolerance = self.get_tolerance()
        d = self.canvas.mapUnitsPerPixel()
        geom = geom.simplify(tolerance * d)
        self.setRubberBandGeom(geom, self.rb)


    def createFeature(self, geom, feat):
        continueFlag = False
        layer = self.canvas.currentLayer()
        provider = layer.dataProvider()

        self.check_crs()
        if self.layerCRSSrsid != self.projectCRSSrsid:
            geom.transform(QgsCoordinateTransform(self.projectCRSSrsid, self.layerCRSSrsid))

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
            if layer.geometryType() == QGis.Line:
                layer.addFeature(f)
                layer.endEditCommand()
            else:
                QMessageBox.warning(None, "Warning", "Select Line layer!")
        else:
            dlg = self.iface.getFeatureForm(layer, f)
            if dlg.exec_():
                if layer.geometryType() == QGis.Line:
                    layer.endEditCommand()
                else:
                    QMessageBox.warning(None, "Warning", "Select Line layer!")
                    layer.destroyEditCommand()
                    continueFlag = True
            else:
                layer.destroyEditCommand()
                reply = QMessageBox.question(None, "Question", "continue?", QMessageBox.Yes,
                                             QMessageBox.No)
                if reply == QMessageBox.Yes:
                    continueFlag = True
            return continueFlag


    def editFeature(self, geom, f, hidedlg):
        layer = self.canvas.currentLayer()
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
            return False,None
        else:
            return True,f[0]

    def check_selection(self,layer):
        featid_list = layer.selectedFeaturesIds()
        if len(featid_list) > 0:
            return True,featid_list
        else:
            return False,featid_list

    def selectNearFeature(self,layer,pnt):
        #近い地物を選択
        layer.removeSelection()
        near, f = self.getNearFeature(layer,pnt)
        if near:
            featid = f.id()
            layer.select(featid)
            return True,f
        else:
            return False,None

    def getSelectedNearFeature(self,layer,pnt):
        selected, featids = self.check_selection(layer)
        near, f = self.getNearFeature(layer,pnt)
        if selected and near and featids[0]==f.id():
            return True,f
        else:
            return False,None

    def canvasPressEvent(self, event):
        layer = self.canvas.currentLayer()
        if not layer:
            return
        if layer.type() != QgsMapLayer.VectorLayer:
            return
        button_type = event.button()
        self.check_snapsetting()
        snapped,pnt = self.getSnapPoint(event,layer)
        #右クリック
        if button_type==2:
            #新規の確定
            if self.state=="plotting" and self.modify==False:
                self.finish_drawing()
            #編集の確定
            elif self.state=="plotting" and self.modify==True and self.rb is not None:
                layer.removeSelection()
                self.finish_editing()
            # 近い地物を選択
            else:
                selected,f = self.getSelectedNearFeature(layer, pnt)
                # altを押しながらで切断（選択地物）
                if self.alt and selected:
                    geom = QgsGeometry(f.geometry())
                    self.check_crs()
                    if self.layerCRSSrsid != self.projectCRSSrsid:
                        geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
                    near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt, geom)
                    polyline = geom.asPolyline()
                    line1 = polyline[0:afterVertex]
                    line1.append(minDistPoint)
                    line2 = polyline[afterVertex:]
                    line2.insert(0, minDistPoint)
                    self.createFeature(QgsGeometry.fromPolyline(line2), f)
                    self.editFeature(QgsGeometry.fromPolyline(line1), f, True)
                    self.canvas.currentLayer().removeSelection()
                # 属性ポップアップ
                elif selected:
                    layer.beginEditCommand("edit attribute")
                    dlg = self.iface.getFeatureForm(layer, f)
                    if dlg.exec_():
                        layer.endEditCommand()
                    else:
                        layer.destroyEditCommand()
                    layer.removeSelection()
                    self.state = "free"
                    self.modify = False
                    self.featid = None
                #選択
                else:
                    layer.removeSelection()
                    near,f = self.selectNearFeature(layer,pnt)
                    # 編集開始（選択地物）
                    if near:
                        self.state = "plotting"
                        self.modify = True
                        self.featid = f.id()
                    else:
                        self.state = "free"
                        self.modify = False
                        self.featid = None


        #左クリック
        elif button_type == 1:

            f = self.getFeatureById(layer, [self.featid])
            # 選択した地物を削除していた場合はfreeに戻す
            if self.featid is not None and f is None:
                self.state = "free"
                self.modify = False
                self.featid = None

            if self.state=="free":
                self.set_rb()
                self.rb.addPoint(pnt) #最初のポイントは同じ点が2つ追加される仕様？
                self.startmarker.setCenter(pnt)
                self.startmarker.show()
                self.startpoint = pnt
                self.state="dragging"
                self.drawingline =[]
                self.drawingidx = 0
                self.edit_drawingidx = 0
            elif self.state == "plotting":
                if self.modify and self.rb is None:
                    layer.removeSelection()
                    #  rbに変換して、編集処理
                    f = self.getFeatureById(layer, [self.featid])
                    geom = QgsGeometry(f.geometry())
                    self.check_crs()
                    if self.layerCRSSrsid != self.projectCRSSrsid:
                        geom.transform(QgsCoordinateTransform(self.layerCRSSrsid, self.projectCRSSrsid))
                    self.set_rb()
                    self.setRubberBandGeom(geom, self.rb)


                # 作成中のrbのラインに近いか
                geom = self.rb.asGeometry()
                near, minDistPoint, afterVertex = self.closestPointOfGeometry(pnt, geom)
                # 編集開始（未確定地物）
                if near:
                    rbgeom = self.rb.asGeometry()
                    self.setRubberBandGeom(rbgeom, self.rb)
                    self.set_edit_rb()
                    self.edit_rb.addPoint(pnt)
                    self.state="editing"
                # プロット
                else:
                    if self.state=="editing":
                        self.edit_rb.addPoint(pnt)
                    else:
                        self.rb.addPoint(pnt)
                        self.drawingidx = self.rb.numberOfVertices() - 1

                    self.state="dragging"
                    self.drawingline = []

    #描画の開始ポイントとのスナップを調べる
    def getSelfSnapPoint(self,point):
        if self.startpoint is not None:
            p = self.startpoint
            d = self.canvas.mapUnitsPerPixel() * 4
            if (p.x() - d <= point.x() <= p.x() + d) and (p.y() - d <= point.y() <= p.y() + d):
                self.snapmarker.setCenter(p)
                self.snapmarker.show()
                return True,p
        return False,None

    # # 描画中のすべての点とスナップを調べる場合
    # def getSelfSnapPoint(self,point):
    #     if self.rb is not None:
    #         rbgeom = self.rb.asGeometry()
    #         rbline = rbgeom.asPolyline()
    #         for p in rbline:
    #             d = self.canvas.mapUnitsPerPixel() * 4
    #             if (p.x() - d <= point.x() <= p.x() + d) and (p.y() - d <= point.y() <= p.y() + d):
    #                 self.snapmarker.setCenter(p)
    #                 self.snapmarker.show()
    #                 return True,p
    #     return False,None

    def getSnapPoint(self,event,layer):
        snaptype = [False, False]
        self.snapmarker.hide()
        point = event.pos()
        pnt = self.toMapCoordinates(point)
        if self.snapping:
            snapper = QgsMapCanvasSnapper(self.canvas)
            (retval, snapped) = snapper.snapToBackgroundLayers(point)
            if snapped !=[]:
                snppoint = snapped[0].snappedVertex
                self.snapmarker.setCenter(snppoint)
                self.snapmarker.show()
                #ここのpointはQgsPointになっているので、layerが必要
                pnt = self.toMapCoordinates(layer,snppoint)
                snaptype[0] = True
        point = self.toMapCoordinates(point)
        snapped,point =  self.getSelfSnapPoint(point)
        if snapped:
            pnt = point
            snaptype[1] = True
        return snaptype,pnt

    def canvasMoveEvent(self, event):
        layer = self.canvas.currentLayer()
        if not layer:
            return
        if layer.type() != QgsMapLayer.VectorLayer:
            return
        snaptype,pnt = self.getSnapPoint(event,layer)
        #作成中、編集中
        if self.state=="dragging":
            self.rb.addPoint(pnt)
            self.drawingline.append(pnt)
        elif self.state=="editing":
            self.edit_rb.addPoint(pnt)
            self.drawingline.append(pnt)

    def canvasReleaseEvent(self, event):
        layer = self.canvas.currentLayer()
        if not layer:
            return
        # ドロー終了
        if (self.state == "dragging" or self.state == "editing"):
            snaptype,pnt = self.getSnapPoint(event,layer)
            if self.state=="editing":
                #線上にプロットする場合。一旦、modifyになっているので、プロットならプロット処理をする
                if self.edit_rb.numberOfVertices() == 2:
                    #既存のオブジェを修正する場合。

                    self.rb.addPoint(pnt)
                else:
                    editedgeom = self.rb.asGeometry()
                    rbgeom = self.edit_rb.asGeometry()
                    self.modify_obj(rbgeom, editedgeom)
                    # スナップしていたらスムーズ処理で消えた分を直線で結ぶ
                    if snaptype[0]:
                        self.rb.addPoint(pnt)
                    self.edit_rb.reset()
                    self.edit_rb = None
            elif self.state=="dragging":
                #スムーズ処理してrbを付け替える
                if len(self.drawingline) > 0:
                    rbgeom = self.rb.asGeometry()
                    rbline = rbgeom.asPolyline()
                    rbline[self.drawingidx + 1:] = self.smoothing(self.drawingline)
                    geom = QgsGeometry().fromPolyline(rbline)
                    tolerance = self.get_tolerance()
                    d = self.canvas.mapUnitsPerPixel()
                    geom = geom.simplify(tolerance * d)
                    self.setRubberBandGeom(geom,self.rb)
                    #スナップしていたらスムーズ処理で消えた分を直線で結ぶ
                    if snaptype[0] or snaptype[1]:
                        self.rb.addPoint(pnt)
            self.state = "plotting"


    def setRubberBandGeom(self, geom, rb):
        points = geom.asPolyline()
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
            if f is not None:
                self.editFeature(geom, f,False)
        # reset rubberband and refresh the canvas
        self.state = "free"
        self.modify = False
        self.rb.reset()
        self.rb = None
        self.startmarker.hide()
        self.startpoint = None
        self.canvas.refresh()

    def finish_drawing(self):
        if self.rb.numberOfVertices() > 1:
            geom = self.rb.asGeometry()
            continueFlag = self.createFeature(geom, None)
        if continueFlag == False:
            # reset rubberband and refresh the canvas
            self.state = "free"
            self.modify = False
            self.rb.reset()
            self.rb = None
            self.startmarker.hide()
            self.startpoint = None
            self.canvas.refresh()

    def set_rb(self):
        self.rb = QgsRubberBand(self.canvas, QGis.Line)
        self.rb.setColor(QColor(255, 0, 0, 150))
        self.rb.setWidth(2)

    def set_edit_rb(self):
        self.edit_rb = QgsRubberBand(self.canvas, QGis.Line)
        self.edit_rb.setColor(QColor(255, 255, 0, 150))
        self.edit_rb.setWidth(2)

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

    def check_snapsetting(self):
        proj = QgsProject.instance()
        snapmode = proj.readEntry('Digitizing', 'SnappingMode')[0]
        # QgsMessageLog.logMessage("snapmode:{}".format(snapmode), 'MyPlugin', QgsMessageLog.INFO)
        if snapmode == "advanced":
            snaplayer = proj.readListEntry('Digitizing', 'LayerSnappingList')[0]
            snapenabled = proj.readListEntry('Digitizing', 'LayerSnappingEnabledList')[0]
            snapavoid = proj.readListEntry('Digitizing', 'AvoidIntersectionsList')[0]
            layerid = self.canvas.currentLayer().id()
            if layerid in snaplayer:  # 新規のレイヤーだとない場合がある？
                snaptype = snapenabled[snaplayer.index(layerid)]
                # QgsMessageLog.logMessage("snaptype:{}".format(snaptype), 'MyPlugin', QgsMessageLog.INFO)
                self.snapavoidbool = self.canvas.currentLayer().id() in snapavoid
                if snaptype == "disabled":
                    self.snapping = False
                else:
                    self.snapping = True
            else:
                self.snapping = True
        else:
            snaptype = proj.readEntry('Digitizing', 'DefaultSnapType')[0]
            if snaptype == "off":
                self.snapping = False
            else:
                self.snapping = True
            self.snapavoidbool = False

    def showSettingsWarning(self):
        pass

    def activate(self):
        self.cursor = QCursor()
        self.cursor.setShape(Qt.ArrowCursor)
        self.canvas.setCursor(self.cursor)
        self.alt = False
        self.snapmarker.setColor(QColor(0, 0, 255))
        self.check_snapsetting()

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

