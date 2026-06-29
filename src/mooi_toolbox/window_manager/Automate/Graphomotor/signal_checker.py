from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class SignalStatus:
    stream_ok: bool = False
    eda_ok: bool = False
    ecg_ok: bool = False
    eda_message: str = "EDA: waiting"
    ecg_message: str = "ECG: waiting"
    stream_message: str = "OpenSignals: waiting"
    last_sample_age_sec: Optional[float] = None


class OpenSignalsHealthChecker:
    """
    Live checker for OpenSignals LSL data.

    Based on the lab-PC test:
        OpenSignals has 3 channels at 1000 Hz
        EDA = sample[0]
        ECG = sample[2]

    This checks the actual incoming samples, not only whether LabRecorder sees the stream.
    """

    def __init__(
        self,
        stream_name: str = "OpenSignals",
        eda_index: int = 0,
        ecg_index: int = 2,
        check_every_sec: float = 2.0,
        window_sec: float = 10.0,
        on_status: Optional[Callable[[SignalStatus], None]] = None,
    ) -> None:
        self.stream_name = stream_name
        self.eda_index = eda_index
        self.ecg_index = ecg_index
        self.check_every_sec = check_every_sec
        self.window_sec = window_sec
        self.on_status = on_status

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.latest_status = SignalStatus()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait_for_good_signal(self, timeout_sec: float = 30.0) -> bool:
        """
        Wait until both EDA and ECG are healthy, or until timeout.
        Useful before starting LabRecorder.
        """
        start = time.time()
        while time.time() - start < timeout_sec:
            status = self.latest_status
            if status.stream_ok and status.eda_ok and status.ecg_ok:
                return True
            time.sleep(0.5)
        return False

    def _publish(self, status: SignalStatus) -> None:
        self.latest_status = status
        if self.on_status:
            self.on_status(status)

    def _run(self) -> None:
        try:
            from pylsl import StreamInlet, resolve_byprop
        except Exception as e:
            self._publish(
                SignalStatus(
                    stream_ok=False,
                    stream_message=f"OpenSignals checker error: pylsl not available ({e})",
                    eda_message="EDA: not checked",
                    ecg_message="ECG: not checked",
                )
            )
            return

        inlet = None

        while not self._stop_event.is_set():
            try:
                if inlet is None:
                    self._publish(
                        SignalStatus(
                            stream_ok=False,
                            stream_message="OpenSignals: searching...",
                            eda_message="EDA: waiting",
                            ecg_message="ECG: waiting",
                        )
                    )

                    streams = resolve_byprop("name", self.stream_name, timeout=3)
                    if not streams:
                        time.sleep(1)
                        continue

                    inlet = StreamInlet(streams[0], max_buflen=30)

                status = self._check_window(inlet)
                self._publish(status)
                time.sleep(self.check_every_sec)

            except Exception as e:
                inlet = None
                self._publish(
                    SignalStatus(
                        stream_ok=False,
                        stream_message=f"OpenSignals: disconnected/error ({e})",
                        eda_message="EDA: not checked",
                        ecg_message="ECG: not checked",
                    )
                )
                time.sleep(2)

    def _check_window(self, inlet) -> SignalStatus:
        deadline = time.time() + self.window_sec
        eda_values: list[float] = []
        ecg_values: list[float] = []
        last_sample_time: Optional[float] = None

        while time.time() < deadline and not self._stop_event.is_set():
            sample, timestamp = inlet.pull_sample(timeout=0.5)

            if not sample:
                continue

            last_sample_time = time.time()

            if len(sample) <= max(self.eda_index, self.ecg_index):
                return SignalStatus(
                    stream_ok=True,
                    eda_ok=False,
                    ecg_ok=False,
                    stream_message=f"OpenSignals: wrong channel count ({len(sample)})",
                    eda_message="EDA: missing channel",
                    ecg_message="ECG: missing channel",
                    last_sample_age_sec=0,
                )

            eda_values.append(float(sample[self.eda_index]))
            ecg_values.append(float(sample[self.ecg_index]))

        if last_sample_time is None:
            return SignalStatus(
                stream_ok=False,
                eda_ok=False,
                ecg_ok=False,
                stream_message="OpenSignals: no new samples",
                eda_message="EDA: no data",
                ecg_message="ECG: no data",
                last_sample_age_sec=None,
            )

        age = time.time() - last_sample_time

        eda_ok, eda_msg = self._check_eda(eda_values)
        ecg_ok, ecg_msg = self._check_ecg(ecg_values)

        return SignalStatus(
            stream_ok=True,
            eda_ok=eda_ok,
            ecg_ok=ecg_ok,
            stream_message="OpenSignals: receiving samples",
            eda_message=eda_msg,
            ecg_message=ecg_msg,
            last_sample_age_sec=age,
        )

    @staticmethod
    def _safe_range(values: list[float]) -> float:
        if not values:
            return 0.0
        return max(values) - min(values)

    @staticmethod
    def _safe_stdev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return statistics.pstdev(values)

    def _check_eda(self, values: list[float]) -> tuple[bool, str]:
        if len(values) < 100:
            return False, "EDA: too few samples"

        signal_range = self._safe_range(values)
        signal_sd = self._safe_stdev(values)

        # EDA is slow, so use lenient thresholds.
        # Your test showed range around 10,000 over 10 sec, so this is conservative.
        if signal_range < 5 and signal_sd < 1:
            return False, "EDA: flat/frozen"

        return True, f"EDA: OK (range {signal_range:.1f})"

    def _check_ecg(self, values: list[float]) -> tuple[bool, str]:
        if len(values) < 100:
            return False, "ECG: too few samples"

        signal_range = self._safe_range(values)
        signal_sd = self._safe_stdev(values)

        # Your test showed ECG range about 2.8, so this catches flat/disconnected signal.
        if signal_range < 0.05 or signal_sd < 0.005:
            return False, "ECG: flat/frozen"

        # Very large constant-ish values often mean saturation or bad contact.
        if signal_range > 20:
            return False, "ECG: possible clipping/saturation"

        return True, f"ECG: OK (range {signal_range:.3f})"


def print_status(status: SignalStatus) -> None:
    age = "unknown" if status.last_sample_age_sec is None else f"{status.last_sample_age_sec:.1f}s"
    print(
        f"{status.stream_message} | {status.eda_message} | {status.ecg_message} | last sample age: {age}",
        flush=True,
    )


if __name__ == "__main__":
    checker = OpenSignalsHealthChecker(on_status=print_status)
    checker.start()

    print("Checking OpenSignals continuously. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        checker.stop()
        print("Stopped.")
