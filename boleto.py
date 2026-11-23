
import json
import socket
import sys
import threading
import time

TOKEN = "uteq-2026"

NODOS = {
    1: ("Quevedo", 6001),
    2: ("Buena Fe", 6002),
    3: ("Valencia", 6003)
}

HOST = "127.0.0.1"
TIMEOUT = 2.0

def enviar(puerto, msg, timeout=TIMEOUT):
    msg["token"] = TOKEN
    

    with socket.create_connection((HOST, puerto), timeout=timeout) as s:
        s.sendall((json.dumps(msg) + "\n").encode())

        with s.makefile() as f:
            linea = f.readline()

    return json.loads(linea) if linea else None

class Nodo:

    def __init__(self, nid):
        self.id = nid
        self.nombre, self.puerto = NODOS[nid]

        self.reloj = 0
        self.vendidos = {}
        self.bloqueados = {}

        self.coordinador = max(NODOS)

        self.lock = threading.Lock()
        self.lock_venta = threading.Lock()
        self.lock_eleccion = threading.Lock()

        self.eligiendo = False

    # ---------- RELOJ DE LAMPORT ----------

    def tick(self):
        with self.lock:
            self.reloj += 1
            return self.reloj

    def recibir_reloj(self, otro):
        with self.lock:
            self.reloj = max(self.reloj, otro) + 1
            return self.reloj

    def log(self, texto):
        with self.lock:
            reloj = self.reloj

        print(
            f"[{self.nombre} | L=({reloj},{self.id})] {texto}",
            flush=True
        )

    def a(self, nid, msg, timeout=TIMEOUT):
        msg = msg.copy()
        msg["lamport"] = self.tick()
        msg["origen"] = self.id

        respuesta = enviar(NODOS[nid][1], msg, timeout)

        if respuesta and "lamport" in respuesta:
            self.recibir_reloj(respuesta["lamport"])

        return respuesta

    # ---------- SERVIDOR ----------

    def servir(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        srv.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_REUSEADDR,
            1
        )

        srv.bind((HOST, self.puerto))
        srv.listen()

        self.log(
            f"escuchando en {self.puerto}; "
            f"coordinador inicial: nodo {self.coordinador}"
        )

        while True:
            conn, _ = srv.accept()

            threading.Thread(
                target=self.atender,
                args=(conn,),
                daemon=True
            ).start()

    def atender(self, conn):
        with conn:
            with conn.makefile() as f:
                linea = f.readline()

            if not linea:
                return

            try:
                msg = json.loads(linea)

                if msg.get("token") != TOKEN:
                    resp = {
                        "ok": False,
                        "error": "token inválido"
                    }
                else:
                    if "lamport" in msg:
                        self.recibir_reloj(msg["lamport"])

                    resp = self.procesar(msg)

            except Exception as e:
                resp = {
                    "ok": False,
                    "error": str(e)
                }

            resp["lamport"] = self.tick()

            conn.sendall(
                (json.dumps(resp) + "\n").encode()
            )

    def procesar(self, m):
        t = m["tipo"]

        if t == "LATIDO":
            return {"ok": True}

        if t == "ESTADO":
            with self.lock:
                return {
                    "ok": True,
                    "nodo": self.nombre,
                    "coordinador": self.coordinador,
                    "vendidos": dict(self.vendidos),
                    "bloqueados": dict(self.bloqueados),
                    "reloj": self.reloj
                }

        if t == "VENDER":
            return self.vender(
                m["asiento"],
                m.get("oficina", self.nombre)
            )

        if t == "VENDER_COORD":
            return self.coordinar(
                m["asiento"],
                m["oficina"]
            )

        # ---------- PREPARAR ----------

        if t == "PREPARAR":
            a = str(m["asiento"])

            with self.lock:
                if a in self.vendidos or a in self.bloqueados:
                    self.log(f"PREPARAR {a}: voto NO")
                    return {"voto": "NO"}

                self.bloqueados[a] = m["tx"]

            self.log(f"PREPARAR {a}: voto SI (bloqueado)")

            return {"voto": "SI"}

        # ---------- CONFIRMAR ----------

        if t == "CONFIRMAR":
            a = str(m["asiento"])

            with self.lock:
                self.bloqueados.pop(a, None)
                self.vendidos[a] = m["oficina"]

            self.log(
                f"CONFIRMAR {a}: vendido por {m['oficina']}"
            )

            return {"ok": True}

        # ---------- ABORTAR ----------

        if t == "ABORTAR":
            a = str(m["asiento"])

            with self.lock:
                if self.bloqueados.get(a) == m["tx"]:
                    self.bloqueados.pop(a)

            self.log(f"ABORTAR {a}")

            return {"ok": True}

        # ---------- ELECCION ----------

        if t == "ELECCION":
            threading.Thread(
                target=self.eleccion,
                daemon=True
            ).start()

            return {"ok": True}

        # ---------- COORDINADOR ----------

        if t == "COORDINADOR":
            self.coordinador = m["id"]
            self.eligiendo = False

            self.log(
                f"nuevo coordinador: nodo {m['id']}"
            )

            return {"ok": True}

        return {
            "ok": False,
            "error": "tipo desconocido"
        }

    # ---------- VENTA Y 2PC ----------

    def vender(self, asiento, oficina):
        try:
            if self.coordinador == self.id:
                return self.coordinar(asiento, oficina)

            return self.a(
                self.coordinador,
                {
                    "tipo": "VENDER_COORD",
                    "asiento": asiento,
                    "oficina": oficina
                },
                timeout=8
            )

        except OSError:
            return {
                "ok": False,
                "error": "coordinador caído, reintente tras la elección"
            }

    def coordinar(self, asiento, oficina):

        with self.lock_venta:

            tx = f"{self.id}-{self.tick()}"

            self.log(
                f"2PC {tx}: asiento {asiento} para {oficina}"
            )

            votos = {}

            # FASE 1: PREPARAR

            for nid in NODOS:

                try:
                    if nid == self.id:
                        respuesta = self.procesar({
                            "tipo": "PREPARAR",
                            "asiento": asiento,
                            "tx": tx
                        })
                    else:
                        respuesta = self.a(
                            nid,
                            {
                                "tipo": "PREPARAR",
                                "asiento": asiento,
                                "tx": tx
                            }
                        )

                    votos[nid] = (
                        respuesta.get("voto", "NO")
                        if respuesta else "NO"
                    )

                except OSError:
                    votos[nid] = "CAIDO"

            # DECISIÓN

            decision = (
                "CONFIRMAR"
                if all(v == "SI" for v in votos.values())
                else "ABORTAR"
            )

            self.log(
                f"2PC {tx}: votos {votos} -> {decision}"
            )

            # FASE 2: CONFIRMAR O ABORTAR

            for nid in NODOS:

                msg = {
                    "tipo": decision,
                    "asiento": asiento,
                    "tx": tx,
                    "oficina": oficina
                }

                try:
                    if nid == self.id:
                        self.procesar(msg)
                    else:
                        self.a(nid, msg)

                except OSError:
                    self.log(
                        f"nodo {nid} no recibió {decision}"
                    )

            return {
                "ok": decision == "CONFIRMAR",
                "decision": decision,
                "transaccion": tx,
                "asiento": asiento,
                "oficina": oficina,
                "votos": votos
            }

    # ---------- LATIDOS ----------

    def latidos(self):
        fallos = 0

        while True:
            time.sleep(1)

            if self.coordinador == self.id or self.eligiendo:
                continue

            try:
                self.a(
                    self.coordinador,
                    {"tipo": "LATIDO"},
                    timeout=1
                )

                fallos = 0

            except OSError:
                fallos += 1

                self.log(
                    f"sin latido del coordinador ({fallos}/3)"
                )

                if fallos >= 3:
                    fallos = 0
                    self.eleccion()

    # ---------- ALGORITMO BULLY ----------

    def eleccion(self):

        with self.lock_eleccion:

            if self.eligiendo:
                return

            self.eligiendo = True

        self.log("inicio elección (Bully)")

        mayor_vivo = False

        for nid in NODOS:

            if nid > self.id:

                try:
                    self.a(
                        nid,
                        {"tipo": "ELECCION"},
                        timeout=1
                    )

                    mayor_vivo = True

                except OSError:
                    pass

        if mayor_vivo:
            time.sleep(3)
            self.eligiendo = False
            return

        self.coordinador = self.id

        self.log("soy el nuevo coordinador")

        for nid in NODOS:

            if nid != self.id:

                try:
                    self.a(
                        nid,
                        {
                            "tipo": "COORDINADOR",
                            "id": self.id
                        },
                        timeout=1
                    )

                except OSError:
                    pass

        self.eligiendo = False


# ---------- PROGRAMA PRINCIPAL ----------

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Uso:")
        print("python sistema.py nodo 1")
        print("python sistema.py vender 6001 10")
        print("python sistema.py estado 6001")
        sys.exit(1)

    modo = sys.argv[1]

    if modo == "nodo":

        if len(sys.argv) < 3:
            print("Debe indicar el ID del nodo")
            sys.exit(1)

        n = Nodo(int(sys.argv[2]))

        threading.Thread(
            target=n.latidos,
            daemon=True
        ).start()

        n.servir()

    elif modo == "vender":

        if len(sys.argv) < 4:
            print("Uso: python sistema.py vender PUERTO ASIENTO")
            sys.exit(1)

        print(
            enviar(
                int(sys.argv[2]),
                {
                    "tipo": "VENDER",
                    "asiento": int(sys.argv[3])
                },
                timeout=10
            )
        )

    elif modo == "estado":

        if len(sys.argv) < 3:
            print("Uso: python sistema.py estado PUERTO")
            sys.exit(1)

        print(
            enviar(
                int(sys.argv[2]),
                {"tipo": "ESTADO"}
            )
        )

    else:
        print("Modo desconocido")