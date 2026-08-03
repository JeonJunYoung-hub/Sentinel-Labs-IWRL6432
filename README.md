# IWRL6432 — mmWave 재실 감지 레이더

TI IWRL6432BOOST (60 GHz mmWave) 로 구역별 재실/움직임을 감지하는 작업.
호스트 쪽 Python 툴 + nRF5340 호스트 앱 자리(Zephyr 스켈레톤).

## 데이터를 어떻게 받아오나

**I2C가 아니라 UART다.** IWRL6432는 독립 SoC 라서 (Cortex-M4F + 하드웨어 가속기)
레이더 신호 처리를 자기가 다 하고, **처리된 결과만** TLV 바이너리로 UART에 뱉는다.
호스트는 원시 레이더 데이터를 만질 일이 없다.

```
[IWRL6432 SoC]  --UART-->  [호스트: PC 또는 nRF5340]
   레이더 펌웨어가            매직워드 + 헤더 + TLV 블록 파싱
   FFT/CFAR/presence 처리
```

흐름은 두 방향이 같은 UART를 공유한다:

1. **호스트 → 레이더**: ASCII CLI 명령. `.cfg` 파일을 한 줄씩 보내 프로파일을 설정하고
   `sensorStart` 로 스트리밍 시작.
2. **레이더 → 호스트**: 프레임마다 바이너리 TLV. 매직워드
   `02 01 04 03 06 05 08 07` 로 시작하고, 헤더 뒤에 TLV 타입별 페이로드가 붙는다
   (point cloud, presence, target list, stats).

현재 프로파일은 250 ms 주기 → 약 4 fps.

**핵심 함정: CLI와 데이터가 같은 UART 하나를 쓴다.** IWR6843 계열처럼 "설정 포트 /
데이터 포트 2개"가 아니다. 그래서 cfg 안의 `baudRate 1250000` 은 *지금 말하고 있는 그
포트*의 속도를 바꿔버리고, 그 줄 이후는 새 속도로 보내야 한다.

## 현재 상태

- **1단계 (완료)** — EVM을 맥에 USB 직결. `radar.py` 로 cfg 25/25 줄 수락, TLV 스트림
  수신 및 디코딩 확인.
- **2단계 (예정)** — PC 자리를 nRF5340이 대체. UART로 cfg 보내고 TLV 파싱.
  `src/main.c` 는 아직 빈 Zephyr 스켈레톤이다.

2단계에서는 **UART 2선으로는 부족하다.** 리셋 없이는 재설정이 안 되는 데모라
nRF5340이 IWRL6432의 NRST를 GPIO로 잡아야 한다 (둘 다 3.3V 로직이라 레벨 시프터 불필요).

## 사용법

```bash
cd tools
python3 radar.py iwrl6432-presence.cfg    # warm reset -> cfg 전송 -> 프레임 검증
python3 monitor.py iwrl6432-presence.cfg  # 구역별 재실 라이브 출력
python3 listen.py 5                       # 5초간 프레임 카운트
python3 tlv.py                            # 디코더 자체 검증 (하드웨어 불필요)
```

pyserial 안 쓴다 — stdlib `termios` / `fcntl` 로 충분해서 의존성을 추가하지 않았다.
(1250000 baud는 termios에 상수가 없어서 macOS `IOSSIOSPEED` ioctl로 설정한다.)

## 파일

| 파일 | 역할 |
|---|---|
| `tools/radar.py` | 링크 관리: baud 자동탐지, warm reset, cfg 한 줄씩 전송·검증 |
| `tools/tlv.py` | 프레임/TLV 디코더 (SDK 헤더에서 레이아웃 전사) |
| `tools/monitor.py` | 구역별 재실 라이브 출력 |
| `tools/listen.py` | 프레임 수 / fps 빠른 확인 |
| `tools/iwrl6432-presence.cfg` | presence 프로파일 (동작 확인됨) |
| `src/main.c` | nRF5340 호스트 앱 (2단계, 아직 비어 있음) |

## 자세한 내용

브링업 과정에서 걸린 함정들(펌웨어 버전 불일치, 저전력 모드에서 UART 죽는 문제,
문자 유실, 트래커 미해결 이슈 등)은 **[tools/README.md](tools/README.md)** 에 전부 정리돼
있다. 2단계 작업 전에 읽을 것.

## 관련 저장소

공기질 측정(PM2.5/PM10/VOC/온습도)은 별도 저장소:
[JeonJunYoung-hub/nRF5340_Wearable](https://github.com/JeonJunYoung-hub/nRF5340_Wearable) —
이쪽은 센서를 **I2C** 로 읽는다.
