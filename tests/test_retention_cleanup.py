"""Tests para scheduler/jobs/retention_cleanup.py — job wrapper de scheduler/retention.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _sesiones_sin_bd():
    """Sin BD, la purga de sesiones anota ``-1`` y el job lanzaría por ello."""
    with patch("scheduler.jobs.retention_cleanup._purgar_sesiones_caducadas", return_value=0):
        yield


@pytest.mark.usefixtures("_sesiones_sin_bd")
class TestRunRetentionCleanup:
    @patch("scheduler.retention.run_retention", return_value={"deleted": 10})
    def test_calls_retention(self, mock_retention: MagicMock) -> None:
        """El job sigue devolviendo lo que devuelve la purga de tablas.

        Desde S8.1 el resultado se ensancha con el desglose de binarios, así
        que la aserción es de inclusión y no de igualdad: lo que este test
        protege es que el resultado de ``run_retention`` llegue intacto al
        llamador, no que nadie pueda añadir contadores nuevos.
        """
        from scheduler.jobs.retention_cleanup import run

        result = run()
        assert result["deleted"] == 10
        mock_retention.assert_called_once()

    @patch("scheduler.retention.run_retention", return_value={"deleted": 0})
    def test_cuenta_los_binarios_purgados(self, _mock_retention: MagicMock) -> None:
        """Criterio de aceptación de S8.1: la purga de binarios **se cuenta**.

        Sin almacén de objetos configurado —el caso de este entorno y el de
        cualquier despliegue que aún no haya hecho el cutover— los tres
        contadores existen y valen cero. Que existan es lo que hace auditable
        la purga: un job que no dice cuánto purgó no se puede vigilar.
        """
        from scheduler.jobs.retention_cleanup import run

        blobs = run()["documento_blobs"]
        assert set(blobs) == {"candidatos", "borrados", "claves_olvidadas"}
        assert all(isinstance(v, int) for v in blobs.values())


class TestPurgaDeSesiones:
    """``purge_expired_sessions`` existía sin llamador: la tabla solo crecía."""

    @patch("scheduler.jobs.retention_cleanup._purgar_binarios_expedientes_cerrados")
    @patch("scheduler.retention.run_retention", return_value={})
    @patch("db.sessions.purge_expired_sessions", return_value=7)
    def test_el_job_purga_las_sesiones_y_lo_cuenta(
        self, mock_purga: MagicMock, _retention: MagicMock, _blobs: MagicMock
    ) -> None:
        from scheduler.jobs.retention_cleanup import run

        assert run()["sessions"] == 7
        mock_purga.assert_called_once_with()

    @patch("db.sessions.purge_expired_sessions", side_effect=RuntimeError("bd caída"))
    def test_un_fallo_no_tumba_el_resto_de_la_retencion(self, _purga: MagicMock) -> None:
        from scheduler.jobs.retention_cleanup import _purgar_sesiones_caducadas

        assert _purgar_sesiones_caducadas() == -1


class TestUnaTablaFallidaFallaElPaso:
    """Un ``-1`` no puede dejar el paso en verde (y el lock diario puesto)."""

    @patch("scheduler.jobs.retention_cleanup._purgar_sesiones_caducadas", return_value=0)
    @patch("scheduler.jobs.retention_cleanup._purgar_binarios_expedientes_cerrados")
    @patch("scheduler.retention.run_retention", return_value={"audit_log": 4, "access_log": -1})
    def test_lanza_tras_intentar_todas(
        self, _retention: MagicMock, blobs: MagicMock, sesiones: MagicMock
    ) -> None:
        from scheduler.jobs.retention_cleanup import run
        from scheduler.retention import RetencionIncompleta

        with pytest.raises(RetencionIncompleta, match="access_log"):
            run()
        # Lo que va después de la tabla rota se intentó igualmente.
        blobs.assert_called_once()
        sesiones.assert_called_once()

    @patch("scheduler.jobs.retention_cleanup._purgar_sesiones_caducadas", return_value=-1)
    @patch("scheduler.jobs.retention_cleanup._purgar_binarios_expedientes_cerrados")
    @patch("scheduler.retention.run_retention", return_value={"audit_log": 0})
    def test_las_sesiones_fallidas_tambien_cuentan(self, *_mocks: MagicMock) -> None:
        from scheduler.jobs.retention_cleanup import run
        from scheduler.retention import RetencionIncompleta

        with pytest.raises(RetencionIncompleta, match="sessions"):
            run()

    def test_el_cierre_suelta_el_lock_diario_si_la_retencion_falla(self) -> None:
        """``_run_periodic`` libera el lock al propagar: la pasada siguiente reintenta."""
        from scheduler.pipeline_runs import _run_retention_cleanup
        from scheduler.retention import RetencionIncompleta

        with (
            patch("db.job_locks.acquire", return_value=True),
            patch("db.job_locks.release") as release,
            patch(
                "scheduler.jobs.retention_cleanup.run",
                side_effect=RetencionIncompleta("retención incompleta"),
            ),
            pytest.raises(RetencionIncompleta),
        ):
            _run_retention_cleanup()
        release.assert_called_once()
