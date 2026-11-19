from nexo_mcp.catalogo import papel_de


def test_solo_marts_marcados(catalogo):
    # dim_cuenta_contable no está marcado; stg_resiplus__estancias está marcado pero fuera de marts/
    assert list(catalogo.vistas()) == ["operaciones__ocupacion"]


def test_papeles_por_descripcion(vista):
    assert [c.nombre for c in vista.de_papel("dimension")] == ["fecha", "codigo_centro", "territorio"]
    assert [c.nombre for c in vista.de_papel("metrica")] == ["plazas_ocupadas_provisional", "camas_activas"]
    assert [c.nombre for c in vista.de_papel("tecnica")] == ["fecha_corte", "construido_en"]
    assert vista.columnas["centro_en_maestro"].papel == "control"


def test_papel_sin_prefijo():
    assert papel_de("Algo sin prefijo") == "otra"
    assert papel_de("  dimension. sin tilde") == "dimension"


def test_resumen_lleva_aviso_y_primer_parrafo(vista):
    resumen = vista.resumen()
    assert resumen["aviso"] == "Demo. Reglas provisionales."
    assert resumen["estado"] == "demo"
    assert resumen["descripcion"] == "Ocupación de los centros residenciales por centro y día."
