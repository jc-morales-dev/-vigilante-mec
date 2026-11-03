"""Certificados para HTTPS en Linux.

El OpenSSL que PyInstaller empaqueta busca los certificados donde estaban en la máquina que
construyó la app (/usr/lib/ssl, Ubuntu). En Fedora, Arch, openSUSE... esa carpeta no existe y
toda conexión falla con CERTIFICATE_VERIFY_FAILED. Por eso se le indica el archivo correcto.

Primero los del sistema (incluyen los que haya añadido un antivirus o el proxy de una empresa);
si no hay ninguno, los que trae la app (certifi).
"""
import os

RUTAS_SISTEMA = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Mint, Arch, Fedora reciente
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora antiguo, RHEL, CentOS
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # otras
)


def _con_contenido(ruta):
    try:
        return os.path.getsize(ruta) > 0
    except OSError:
        return False


def configurar():
    """Debe llamarse antes de la primera conexión. Los procesos hijos heredan el ajuste."""
    if os.name == "nt" or _con_contenido(os.environ.get("SSL_CERT_FILE", "")):
        return
    for ruta in RUTAS_SISTEMA:
        if _con_contenido(ruta):
            os.environ["SSL_CERT_FILE"] = ruta
            return
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass


def probar(urls):
    """Para las pruebas automáticas: si un certificado no se puede verificar, termina con error."""
    import urllib.error
    import urllib.request
    for url in urls:
        try:
            urllib.request.urlopen(url, timeout=30).close()
        except urllib.error.HTTPError:
            pass  # el servidor respondió: el certificado ya se verificó
    print("CONEXION_OK", os.environ.get("SSL_CERT_FILE", ""), flush=True)
