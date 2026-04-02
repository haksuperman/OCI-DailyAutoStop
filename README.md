# OCI AutoStop Python App

Oracle Linux 환경에서 cron으로 실행하는 OCI AutoStop 애플리케이션이다. tenancy 범위 또는 DEV 기준 subtree 범위를 조회하고, exception 파일에 기록된 compartment subtree를 제외한 뒤 Compute Instance, DB Node, Autonomous Database 중 실행 대상 상태의 리소스만 정지한다.

## 주요 특징

- OCI Python SDK 기반 구현
- `dev` / `prod` 모드 전환 지원
- `prod`에서 tenancy subscribed region 자동 탐색
- region exclusion 및 discovery 실패 시 fallback 지원
- exception 파일 기반 compartment subtree 제외
- dry-run 지원
- OCI API 재시도와 backoff 적용
- 컴파트먼트별 상세 로그와 최종 summary 로그 출력
- 컴파트먼트 내부 리전 작업 병렬 처리 지원
- `execution.max_workers` 기반 region 병렬 개수 제어
- root compartment 직접 생성 리소스 포함 여부 제어
- 일부 region 또는 resource 실패가 전체 실행을 즉시 중단시키지 않도록 설계

## 디렉토리 구조

```text
app/
  __init__.py
  compartments.py
  config.py
  logging_utils.py
  main.py
  models.py
  oci_clients.py
  reporting.py
  resources.py
  retry.py
  service.py
config/
  autostop_compartment_exception.txt
  settings.yaml
logs/
tests/
requirements.txt
README.md
```

## 설치

Oracle Linux 예시:

```bash
sudo dnf install -y python3 python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

OCI API 인증은 서버의 `~/.oci/config` 와 API key 또는 Instance Principal 정책에 맞게 준비한다. 현재 기본 코드는 `~/.oci/config` 프로파일을 사용한다.

## 설정

기본 설정 파일은 `config/settings.yaml` 이다.

- `scope.mode: dev`
  - `oci.regions` 에 명시한 리전만 대상으로 사용
  - `scope.dev_base_compartment_name_or_ocid` 기준 subtree만 조회
  - tenancy 전체 subtree를 조회하지 않음
- `scope.mode: prod`
  - tenancy subscribed region 전체를 런타임에 자동 조회
  - tenancy 전체 subtree를 조회
  - exception 파일을 반드시 반영
- `oci.excluded_regions`
  - dev/prod 공통으로 실행 대상에서 제외할 리전 목록
  - prod에서 자동 탐색된 리전에도 적용됨
- `oci.regions`
  - dev에서는 실제 실행 리전 목록
  - prod에서는 region discovery 실패 시 fallback 리전 목록
- `scope.include_root_resources`
  - `true`면 root compartment 직접 생성 리소스도 대상에 포함
- `execution.max_workers`
  - 한 컴파트먼트 내부에서 동시에 처리할 region worker 개수
  - 현재 구현은 컴파트먼트는 순차 처리하고, 각 컴파트먼트 안의 region만 병렬 처리함

예외 파일은 `config/autostop_compartment_exception.txt` 이며 주석과 빈 줄을 허용한다.

- 각 줄에는 compartment OCID 또는 exact compartment name 하나를 기록한다.
- 해당 compartment 본인과 하위 subtree 전체가 실행 대상에서 제외된다.
- root compartment를 exception 파일에 넣는 사용 방식은 전제하지 않는다.

## 실행

기본 실행:

```bash
python3 -m app.main --config config/settings.yaml
```

dry-run 강제:

```bash
python3 -m app.main --config config/settings.yaml --dry-run
```

## cron 예시

매일 18:30 실행:

```cron
30 18 * * * cd /home/autostop/OCI-AutoStop && /home/autostop/OCI-AutoStop/.venv/bin/python -m app.main --config config/settings.yaml >> /home/autostop/OCI-AutoStop/logs/cron_stdout.log 2>&1
```

## 동작 순서

1. 설정 로드
2. OCI 설정 로드 및 tenancy 확인
3. 모드에 따라 실행 region 결정
4. 모드에 따라 대상 compartment 범위 결정
5. exception subtree 제외
6. 컴파트먼트 단위로 순차 실행
7. 각 컴파트먼트 내부의 region을 `execution.max_workers` 범위에서 병렬 실행
8. region별로 Compute / DB Node / ADB 조회
9. 상태에 따라 stop 또는 skip
10. stop 후 상태 재확인
11. 수행 완료 파트와 summary details 출력

## 상태 처리 기준

- Compute: `RUNNING` stop, `STOPPED` skip, `STOPPING/STARTING/PROVISIONING` transition skip
- DB Node: `AVAILABLE` stop, `STOPPED` skip, `STOPPING/STARTING/PROVISIONING` transition skip
- ADB: `AVAILABLE` stop, `STOPPED/UNAVAILABLE` skip, `STOPPING/STARTING/PROVISIONING/SCALING` transition skip

## 로그 구조

로그 파일은 기본적으로 `logs/autostop_daily.log` 에 기록된다. 현재 로그 구조는 아래 네 파트로 구성된다.

1. 배너 파트
2. 상세 컴파트먼트별 로그 파트
3. 수행 완료 파트
4. `Summary Details` 파트

컴파트먼트 내부 region 작업은 병렬로 처리하지만, 로그는 worker별로 버퍼링한 뒤 메인 흐름에서 flush하므로 다른 컴파트먼트와 뒤섞이지 않도록 유지한다.

예상 로그 형식 예시는 아래와 같다.

### Dry-run 예시

```text
[2026-04-01 18:30:00] [INFO] ============================================================
[2026-04-01 18:30:00] [INFO] OCI Daily AutoStop (Instance, DB Node, ADB)
[2026-04-01 18:30:00] [INFO]  - Date               : 2026-04-01 18:30:00
[2026-04-01 18:30:00] [INFO]  - Mode               : prod
[2026-04-01 18:30:00] [INFO]  - Dry Run            : true
[2026-04-01 18:30:00] [INFO]  - Target             : 49 compartment(s), 15 region(s)
[2026-04-01 18:30:00] [INFO]  - Regions            : ap-seoul-1, ap-tokyo-1, us-chicago-1
[2026-04-01 18:30:00] [INFO] ============================================================
[2026-04-01 18:30:00] [INFO] OCI Daily AutoStop starting...
[2026-04-01 18:30:00] [INFO] -> Compartment: HOL_TEST
[2026-04-01 18:30:01] [INFO]   [Instance] test-01 (ap-seoul-1) -> Already stopped (no action)
[2026-04-01 18:30:01] [INFO]   [Instance] test-02 (ap-tokyo-1) -> Stop target (dry-run)
[2026-04-01 18:30:01] [INFO]   [ADB] TEST_ADW (us-chicago-1) -> Already stopped (no action)
[2026-04-01 18:30:02] [INFO] -> Compartment: PROD_APP
[2026-04-01 18:30:03] [INFO]   [DB Node] dbnode-01 (ap-seoul-1) -> In transition (STOPPING)
[2026-04-01 18:30:03] [INFO] ============================================================
[2026-04-01 18:30:03] [INFO] Dry-run analysis completed (1 Instance(s), 0 DB Node(s), 0 ADB(s) matched).
[2026-04-01 18:30:03] [INFO] ============================================================
[2026-04-01 18:30:03] [INFO] Summary Details
[2026-04-01 18:30:03] [INFO]  Instances scanned : 12
[2026-04-01 18:30:03] [INFO]   ├─ Already stopped : 10
[2026-04-01 18:30:03] [INFO]   ├─ In transition   : 1
[2026-04-01 18:30:03] [INFO]   └─ Stop targets (Dry-run) : 1
[2026-04-01 18:30:03] [INFO]  DB Nodes scanned : 3
[2026-04-01 18:30:03] [INFO]   ├─ Already stopped : 2
[2026-04-01 18:30:03] [INFO]   ├─ In transition   : 1
[2026-04-01 18:30:03] [INFO]   └─ Stop targets (Dry-run) : 0
[2026-04-01 18:30:03] [INFO]  ADBs scanned : 1
[2026-04-01 18:30:03] [INFO]   ├─ Already stopped : 1
[2026-04-01 18:30:03] [INFO]   ├─ In transition   : 0
[2026-04-01 18:30:03] [INFO]   └─ Stop targets (Dry-run) : 0
[2026-04-01 18:30:03] [INFO] Dry-run completed (total duration: 3s)
[2026-04-01 18:30:03] [INFO] ============================================================
```

### 실제 stop 실행 예시 (`dry-run: false`)

```text
[2026-04-01 18:30:00] [INFO] ============================================================
[2026-04-01 18:30:00] [INFO] OCI Daily AutoStop (Instance, DB Node, ADB)
[2026-04-01 18:30:00] [INFO]  - Date               : 2026-04-01 18:30:00
[2026-04-01 18:30:00] [INFO]  - Mode               : prod
[2026-04-01 18:30:00] [INFO]  - Dry Run            : false
[2026-04-01 18:30:00] [INFO]  - Target             : 49 compartment(s), 15 region(s)
[2026-04-01 18:30:00] [INFO]  - Regions            : ap-seoul-1, ap-tokyo-1, us-chicago-1
[2026-04-01 18:30:00] [INFO] ============================================================
[2026-04-01 18:30:00] [INFO] OCI Daily AutoStop starting...
[2026-04-01 18:30:00] [INFO] -> Compartment: PROD_APP
[2026-04-01 18:30:01] [INFO]   [Instance] app-vm-01 (ap-seoul-1) -> Stop request sent
[2026-04-01 18:30:01] [INFO]   [Instance] app-vm-02 (ap-tokyo-1) -> Already stopped (no action)
[2026-04-01 18:30:02] [INFO] -> Compartment: PROD_DB
[2026-04-01 18:30:03] [INFO]   [DB Node] dbnode-01 (ap-seoul-1) -> Stop request sent
[2026-04-01 18:30:03] [INFO]   [ADB] adb-01 (ap-seoul-1) -> Stop request sent
[2026-04-01 18:30:03] [INFO] ============================================================
[2026-04-01 18:30:03] [INFO] Stop requests completed (1 Instance(s), 1 DB Node(s), 1 ADB(s)).
[2026-04-01 18:30:03] [INFO] ============================================================
[2026-04-01 18:30:03] [INFO] OCI Daily AutoStop verifying stop requests...
[2026-04-01 18:30:03] [INFO] Checking final status for requested resources in 60 seconds...
[2026-04-01 18:31:03] [WARNING] Resource not yet fully stopped at verification time. type=db_node name=dbnode-01 region=ap-seoul-1 state=STOPPING
[2026-04-01 18:31:03] [INFO] ============================================================
[2026-04-01 18:31:03] [INFO] Summary Details
[2026-04-01 18:31:03] [INFO]  Instances scanned : 12
[2026-04-01 18:31:03] [INFO]   ├─ Already stopped : 11
[2026-04-01 18:31:03] [INFO]   ├─ In transition   : 0
[2026-04-01 18:31:03] [INFO]   └─ Stop by AutoStop : 1 → 1 successful
[2026-04-01 18:31:03] [INFO]  DB Nodes scanned : 3
[2026-04-01 18:31:03] [INFO]   ├─ Already stopped : 2
[2026-04-01 18:31:03] [INFO]   ├─ In transition   : 0
[2026-04-01 18:31:03] [INFO]   └─ Stop by AutoStop : 1 → 0 successful
[2026-04-01 18:31:03] [INFO]  ADBs scanned : 1
[2026-04-01 18:31:03] [INFO]   ├─ Already stopped : 0
[2026-04-01 18:31:03] [INFO]   ├─ In transition   : 0
[2026-04-01 18:31:03] [INFO]   └─ Stop by AutoStop : 1 → 1 successful
[2026-04-01 18:31:03] [INFO] AutoStop completed (total duration: 1m 3s)
[2026-04-01 18:31:03] [INFO] ============================================================
```

## 테스트

문법 검사:

```bash
python3 -m py_compile app/*.py tests/*.py
```

단위 테스트:

```bash
python3 -m unittest discover -s tests -v
```

## 운영 팁

- 최초 운영은 `dev` + `default_dry_run: true` 로 시작하는 편이 안전하다.
- `prod + --dry-run`으로 exception subtree와 로그 구조를 먼저 검증하는 것을 권장한다.
- `execution.max_workers`는 기본적으로 보수적으로 유지하고, throttling 로그가 없을 때만 단계적으로 올리는 편이 좋다.
- `execution.post_check_delay_seconds`는 DB Node/ADB가 stop 완료까지 오래 걸릴 수 있다는 점을 고려해 운영 환경에 맞게 조정한다.
- prod에서 region discovery가 실패하면 `oci.regions` 값을 fallback으로 사용한다.
- 운영상 제외가 필요한 region은 `oci.excluded_regions` 에 명시한다.
- 현재 로그는 `logs/autostop_daily.log` 와 `logs/cron_stdout.log` 를 하루 단위 덮어쓰기 방식으로 관리하는 운영을 권장한다.
