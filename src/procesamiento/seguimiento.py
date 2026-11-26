from collections import deque
from itertools import count


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ancho = max(0, min(ax2, bx2) - max(ax1, bx1))
    alto = max(0, min(ay2, by2) - max(ay1, by1))
    interseccion = ancho * alto
    if interseccion == 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - interseccion
    return interseccion / union if union > 0 else 0.0


class Seguidor:
    def __init__(self, iou_minimo=0.3, segundos_sin_ver=1.5, ventana=8, confirmaciones=5):
        if not 1 <= confirmaciones <= ventana:
            raise ValueError("La confirmación debe estar entre uno y el tamaño de la ventana.")
        self.iou_minimo = iou_minimo
        self.segundos_sin_ver = segundos_sin_ver
        self.ventana = ventana
        self.confirmaciones = confirmaciones
        self.pistas = {}
        self._ids = count(1)

    def actualizar(self, cajas, ahora):
        # Expira antes de asociar para no heredar votos de un ave que ya salió.
        for id_pista in [i for i, p in self.pistas.items() if ahora - p["ultimo"] > self.segundos_sin_ver]:
            del self.pistas[id_pista]
        pares = []
        for indice, caja in enumerate(cajas):
            for id_pista, pista in self.pistas.items():
                valor = iou(caja, pista["caja"])
                if valor >= self.iou_minimo:
                    pares.append((valor, indice, id_pista))
        pares.sort(reverse=True)

        asignados = [None] * len(cajas)
        usadas = set()
        for _, indice, id_pista in pares:
            if asignados[indice] is None and id_pista not in usadas:
                asignados[indice] = id_pista
                usadas.add(id_pista)

        for indice, caja in enumerate(cajas):
            if asignados[indice] is None:
                id_pista = next(self._ids)
                self.pistas[id_pista] = {
                    "votos": deque(maxlen=self.ventana), "confirmada": None,
                    "id_avistamiento": None, "especie_registrada": None,
                }
                asignados[indice] = id_pista
            self.pistas[asignados[indice]]["caja"] = caja
            self.pistas[asignados[indice]]["ultimo"] = ahora

        for id_pista in self.pistas.keys() - set(asignados):
            self.observar(id_pista, None)
        return asignados

    def observar(self, id_pista, id_especie):
        pista = self.pistas[id_pista]
        pista["votos"].append(id_especie)
        coincide_registro = pista["especie_registrada"] in (None, id_especie)
        confirmada = id_especie is not None and coincide_registro and pista["votos"].count(id_especie) >= self.confirmaciones
        pista["confirmada"] = id_especie if confirmada else None
        return confirmada
