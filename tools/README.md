# IWRL6432 브링업 노트 (1단계: PC 직결)

TI IWRL6432BOOST를 맥에 USB로 직결해서 Presence 데모를 돌리고 TLV 스트림까지
받아낸 기록. 2단계(nRF5340이 호스트 역할)로 넘어갈 때 필요한 제약도 같이 정리.

## 전체 구조

IWRL6432는 **독립 SoC**다. Cortex-M4F + 하드웨어 가속기(HWA)가 내장돼 있고 레이더
펌웨어가 그 위에서 돌면서 처리된 결과(TLV: point cloud, presence, track 등)를 UART로
내보낸다. nRF5340은 감지 자체에 필요하지 않다.

- **1단계 (완료)** — EVM을 PC USB에 직결. XDS110이 CLI + 데이터 경로를 제공.
- **2단계 (예정)** — PC 자리를 nRF5340이 대체. UART로 cfg를 보내고 TLV를 파싱.

## 확인된 하드웨어 / 펌웨어

```
XDS110    Texas Instruments, VID 0x0451 / PID 0xBEF3, serial RI32, FW 03.00.00.13
Platform  XWRL6432          (TLV 헤더 platform 워드 = 0x000a6432)
Demo      Presence_Demo
SDK       05.05.03.00       (TLV 헤더 version 워드 = 0x05050300)
RFS FW    07.01.00.04
```

맥에 두 개의 CDC 포트가 올라온다:

| 포트 | 용도 |
|---|---|
| `/dev/cu.usbmodemRI321` | **CLI + TLV 데이터 (둘 다)** |
| `/dev/cu.usbmodemRI324` | SoC에 연결 안 됨 — 어떤 baud에서도 조용함 |

## 이 과정에서 걸린 함정들

작업 시간의 대부분이 여기 들어갔다. 2단계에서 그대로 다시 만날 것들.

### 1. CLI와 데이터가 같은 UART를 공유한다

TI 문서와 일반적인 IWR6843 계열 경험을 따라 "config 포트 / data 포트 2개"를 가정하면
틀린다. 이 데모는 **하나의 UART에 CLI와 TLV를 멀티플렉싱**한다. 그래서:

- cfg의 `baudRate 1250000`은 데이터 포트가 아니라 **지금 말하고 있는 그 포트**의 속도를 바꾼다.
  그 줄 이후의 모든 명령은 새 속도로 보내야 한다.
- `baudRate` 명령의 `Done`은 **새 속도로** 돌아온다. 옛 속도에서 읽으면 아무것도 없다.
  실패가 아니다.
- 센서가 스트리밍 중이면 CLI 응답이 바이너리 사이에 묻힌다.

### 2. `lowPowerCfg 1`이면 시작 후 UART로 되돌릴 수 없다

저전력 모드에서는 프레임 사이에 슬립하면서 UART RX를 서비스하지 않는다. 한번
`sensorStart`가 실행되면 `sensorStop`도 `sensorWarmRst`도 안 먹는다. 확인된 증상: TLV는
계속 들어오는데 어떤 명령에도 `Done`도 프롬프트도 없음. **복구는 NRST 또는 USB 재삽입뿐.**

그래서 이 저장소의 cfg는 `lowPowerCfg 0`이다. 전력 측정할 때만 1로 바꿀 것.

### 3. 리셋 없이는 재설정이 안 된다

OOB 데모는 in-place 재설정을 지원하지 않는다. 부팅 후 **첫 cfg만** 실제로 적용된다.
두 번째 cfg를 보내면 **모든 줄이 `Done`을 반환하고 `sensorStart`도 성공하는데 프레임이
단 한 개도 나오지 않는다.** 조용한 실패라서 진단이 어렵다.

→ cfg를 보내기 전에 항상 `sensorWarmRst 0`. `radar.py`가 자동으로 한다.

### 4. 한 줄을 한 번에 쓰면 문자가 유실된다

디바이스가 폴링 루프에서 문자를 에코하는데, 줄 전체가 한꺼번에 도착하면 RX를 흘린다.
에코를 보면 드러난다 — 보낸 `... 1 1 0 0 0 0`이 `... 1 1 00 0 0`으로 돌아온다. 명령은
깨진 채로 파싱되고 `Done`이 안 온다. 실행마다 실패 개수가 달라지는 레이스였다.

→ 문자당 1ms로 흘려보낸다 (`write_slow`).

### 5. "Error가 없으면 성공"은 틀린 판정

이게 위의 문제들을 한동안 다 가렸다. 잘못된 baud에서는 응답이 깨진 바이트라서
`Error`도 `Done`도 없다 → 거짓 성공. **반드시 `Done`의 존재로 판정할 것.**

### 6. 펌웨어 버전과 cfg 버전이 안 맞는다

보드 펌웨어는 05.05.03.00인데 공개된 cfg는 05.05.04.02용이다. 두 군데서 깨졌다:

| cfg 원본 (05.05.04) | 이 보드 (05.05.03) |
|---|---|
| `sigProcChainCfg 64 4 2 2 4 4 0 0.5 0` — 인자 9개 | 8개만 받음. 꼬리 `0` 제거 |
| `rangeSNRCompensation 1 5 11 5 6 ...` | 명령 자체가 없음 (`not recognized`). 삭제 |

`sigProcChainCfg`는 그냥 넘길 수 없는 줄이다 — `motDetMode 2`가 minor-motion(presence)
모드를 켜는 부분이라, 이 줄이 빠지면 presence 감지 자체가 성립하지 않는다.
`rangeSNRCompensation`은 05.05.04에서 추가된 SNR 튜닝 항목이라 빠져도 기본값으로 동작한다.

### 7. macOS 관련

- **MMWAVE-L-SDK은 Windows/Linux 인스톨러만 있다.** 맥 버전 없음. 다만 지금은 데모가
  이미 flash돼 있어서 빌드가 필요 없고, cfg는 그냥 텍스트라 상관없다. SDK가 실제로
  필요해지는 건 펌웨어를 다시 빌드할 때뿐이다.
- **1250000 baud는 termios에 상수가 없다.** `IOSSIOSPEED` ioctl(`0x80085402`)로
  설정해야 한다. `set_baud()`가 처리.
- pyserial 미설치 — stdlib `termios`/`fcntl`로 충분해서 의존성 추가하지 않았다.

## 파일

| 파일 | 역할 |
|---|---|
| `radar.py` | 링크 관리: baud 자동탐지, warm reset, cfg 한 줄씩 전송·검증 |
| `tlv.py` | 프레임/TLV 디코더. 레이아웃 전부 SDK 헤더에서 전사, `python3 tlv.py`로 자체 검증 |
| `monitor.py` | 구역별 재실 라이브 출력 |
| `listen.py` | 프레임 수/fps만 빠르게 확인 |
| `iwrl6432-presence.cfg` | presence 프로파일 (동작 확인됨) |
| `iwrl6432-tracking.cfg` | 트래킹 프로파일 (**미해결**, 아래 참고) |

## 사용법

```bash
cd tools
python3 radar.py iwrl6432-presence.cfg    # warm reset -> cfg 전송 -> 프레임 검증
python3 monitor.py iwrl6432-presence.cfg  # 설정 후 구역별 재실 라이브 출력
python3 monitor.py                        # 이미 돌고 있는 센서에 붙기
python3 listen.py 5                       # 5초간 프레임 카운트
python3 tlv.py                            # 디코더 자체 검증 (하드웨어 불필요)
echo version | python3 radar.py -          # 단일 CLI 명령 (리셋 안 함)
```

`radar.py`는 현재 baud를 모른다고 가정하고 115200 / 1250000을 자동 탐지한다
(`sensorStop`이 멱등하고 스트림도 멈추므로 프로브 겸용).

기대 출력:

```
  --    connected at 115200
  --    warm reset, back at 115200
  ok    sensorStop 0
  ...
  ok    baudRate 1250000  (link ok)
  ok    sensorStart 0 0 0 0

  25/25 accepted
  8256 bytes in 3.0s, 13 frames (4.3 fps)
  version=0x05050300 platform=0x000a6432 packetLen=800 frame=1
```

## 검증된 결과

- 25/25 cfg 줄 수락, 연속 실행에서 재현됨
- 4.0–4.3 fps — cfg의 `frameCfg ... 250`(250ms 주기)과 일치
- TLV magic word `02 01 04 03 06 05 08 07` 확인, 헤더의 version/platform이 보드와 일치
- 매 실행 `frame=1`로 시작 → warm reset이 실제로 걸리고 있다는 증거

## cfg 출처

`apex-creator/berkut` 저장소에 미러된 MMWAVE_L_SDK_05_05_04_02의
`examples/mmw_demo/motion_and_presence_detection/profiles/xwrL64xx-evm/PresenceDetect.cfg`.
`xwrL64xx-evm`이 IWRL6432BOOST(FR4, 2-patch 안테나)용이다. AOP EVM이라면 `xwrL64xx-aop`를
써야 한다.

수정 사항: `sigProcChainCfg` 인자 9→8, `rangeSNRCompensation` 삭제, `lowPowerCfg` 1→0.

## 2단계로 넘어갈 때

- **UART 2선만으로는 부족하다.** `lowPowerCfg 1`이면 시작 후 UART가 죽고, 리셋 없이는
  재설정이 안 되므로 **nRF5340이 IWRL6432의 NRST를 GPIO로 잡아야 한다.** 3.3V 로직이라
  레벨 시프터는 불필요.
- 호스트 쪽 재사용 로직: 문자 단위 전송, `Done` 확인, `baudRate` 이후 속도 전환,
  cfg 전 리셋. 전부 `radar.py`에 있는 그대로.
- 두 갈래 선택:
  - **(A)** nRF5340이 부팅 시 cfg 문자열을 그대로 전송. 펌웨어 수정 불필요, 튜닝 빠름.
  - **(B)** 레이더 펌웨어에 config를 컴파일해 넣어 autostart. 호스트는 파싱만.
    운영 기기에 깔끔하지만 SDK + CCS가 필요하고, 그건 Windows/Linux가 필요하다.
- 이 저장소의 Zephyr 스켈레톤(`src/main.c`, `prj.conf`)은 nRF5340 호스트 앱 자리다.
  레이더 펌웨어는 Zephyr로 빌드할 수 없다(CCS 프로젝트).

## 최종 목표와의 간극: 근로자 수 / 체류 시간

목표 출력은 구역별 `근로자 수` + `체류 시간` (PM2.5/PM10은 별도 공기질 센서 몫).

**현재 presence 프로파일로는 headcount가 나오지 않는다.** `presenceInfo`가 주는
`ENHANCED_PRESENCE`(TLV 315)는 구역당 **2비트 상태**(none/minor/major)일 뿐, 사람 수가
아니다. 체류 시간도 프레임 간에 유지되는 식별자가 없으면 "구역이 몇 초간 점유됐다"까지만
가능하다.

사람 수와 1인 단위 체류 시간에는 **트래커**(`trackingCfg` + `TARGET_LIST` TLV 308)가
필요하다. 트래커는 target별 `tid` + 위치를 주므로:

- 구역은 **호스트 쪽 개념**이 된다 — `monitor.py`의 `ZONES` 사각형에 target 좌표를 넣어
  판정. 구역 경계를 바꿀 때 디바이스는 건드릴 필요가 없다. `mpdBoundaryBox` 4구역 방식은
  트래커를 쓰면 불필요해진다.
- 체류 시간은 `tid`가 처음 보인 시각부터 계산한다 (`monitor.py`의 `Dwell`).

`tlv.py`는 TARGET_LIST(308)를 이미 디코드하고 `monitor.py`도 트래커 모드를 지원하므로,
프로파일만 바뀌면 그대로 동작한다.

### 미해결: `trackingCfg`가 거부된다

`iwrl6432-tracking.cfg`는 26/28에서 멈춘다 — `trackingCfg 1 2 100 3`이 거부되고, 그
결과 `sensorStart`도 실패한다. 실패 후 데모가 hang해서 USB 재삽입이 필요했다.

조사한 것:

- 보드 `help`는 `trackingCfg`를 **6인자**로 표시한다
  (`<enable> <paramSet> <numPoints> <numTracks> <maxDoppler> <framePeriod>`).
- 그런데 SDK 05.05.04의 프로파일과 공개된 다른 IWRL6432 cfg 4종 모두 **4인자**를 쓴다.
  즉 단순한 버전 차이가 아닐 수 있다. (`help` 문구 자체가 부정확한 전례가 있다 —
  `cfarCfg`는 8인자로 표시되지만 12인자가 정상 수락된다.)
- 유력한 가설: **플래시된 이미지가 트래커를 포함하지 않는다.** `version`이
  `Presence_Demo`를 보고하는데, 트래커/분류기가 포함된 빌드는 별개 이미지다. CLI 테이블에
  명령은 있어도 DPU가 없으면 실패할 수 있다.

다음 단계는 거부 시의 **정확한 에러 문구를 확보**하는 것 (인자 개수 문제인지 미지원인지가
갈린다). 미지원이면 트래커 빌드를 새로 플래시해야 하고, 그건 SDK가 필요하므로
Windows/Linux가 필요하다.

또한 SDK 프로파일의 `trackingCfg ... 3`은 **최대 트랙 3개**다. 근로자 수를 세려면 올려야
한다.

## 남은 것

- TLV 파서 (헤더 뒤 TLV 타입별 페이로드: point cloud, presence, stats)
- 데이터시트 `iwrl6432-3.pdf`에서 UART 핀 / NRST 핀 확인 — 텍스트가 CID 폰트로 인코딩돼
  있어 아직 못 읽었다. `brew install poppler` 필요.
