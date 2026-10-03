"""Identificadores de prueba con control válido; no son empresas verificadas."""
def client_fixture(seed):
    # Conserva el índice final de los identificadores de las pruebas existentes.
    base = "20" + str(seed)[-8:]
    total = sum(int(digit) * weight for digit, weight in zip(base, (5,4,3,2,7,6,5,4,3,2)))
    return {"document_type": "RUC", "document_number": base + str((11 - total % 11) % 10)}
