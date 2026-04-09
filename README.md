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

Oracle Linux 예시 (`venv` 사용):

```bash
sudo dnf install -y python3 python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Oracle Linux 예시 (시스템 Python 사용):

```bash
sudo dnf install -y python3 python3-pip
python3 -m pip install -r requirements.txt
```

OCI API 인증은 서버의 `~/.oci/config` 와 API key 또는 Instance Principal 정책에 맞게 준비한다. 기본적으로 `config/settings.yaml` 의 `oci.config_file`, `oci.profile` 설정을 사용한다.

## 배포 후 필수 설정

다른 서버에 레포를 내려받아 사용할 경우, 운영자는 반드시 `config/` 아래 설정을 자기 환경 기준으로 검토하고 수정해야 한다.

### `config/settings.yaml`에서 확인할 항목

- `oci.config_file`
  - OCI 인증 설정 파일 경로
  - 일반적으로 `~/.oci/config` 를 사용하지만 서버마다 다를 수 있다.
- `oci.profile`
  - 사용할 OCI CLI/SDK 프로파일명
  - 각 서버의 `~/.oci/config` 에 실제로 존재하는 프로파일명으로 맞춰야 한다.
- `oci.tenancy_ocid`
  - 대상 tenancy OCID
  - 운영 대상 tenancy와 다르면 잘못된 테넌시를 조회할 수 있다.
- `oci.regions`
  - 실행 또는 fallback에 사용할 region 목록
  - `dev`에서는 실제 실행 대상 region이며, `prod`에서는 auto-discovery 실패 시 fallback으로 사용된다.
- `oci.excluded_regions`
  - 실행에서 제외할 region 목록
  - 운영 정책상 제외할 region이 있으면 명시해야 한다.
- `scope.mode`
  - `dev` 또는 `prod`
  - 테스트/검증 단계면 일반적으로 `dev`, 전체 운영이면 `prod`를 사용한다.
- `scope.dev_base_compartment_name_or_ocid`
  - `dev` 모드에서 기준이 되는 compartment 이름 또는 OCID
  - `dev` 모드에서는 필수 값이다.
- `scope.include_root_resources`
  - root compartment에 직접 생성된 리소스를 포함할지 여부
  - tenancy 구조와 운영 정책에 맞춰 판단해야 한다.
- `scope.exception_file`
  - 제외할 compartment subtree 목록 파일 경로
  - 기본값을 그대로 써도 되지만 파일 내용은 각 환경에 맞게 관리해야 한다.
- `execution.default_dry_run`
  - 기본 실행을 dry-run으로 할지 여부
  - 최초 배포 시에는 `true`로 두고 검증 후 `false`로 전환하는 편이 안전하다.
- `execution.max_workers`
  - 한 컴파트먼트 내부 region 병렬 처리 개수
  - API throttling이나 운영 부하를 고려해 조정해야 한다.
- `execution.post_check_delay_seconds`
  - stop 요청 후 최종 상태 재확인까지 대기할 시간
  - DB Node, ADB 정지 시간이 긴 환경이면 늘릴 수 있다.
- `execution.post_check_max_workers`
  - stop 후 검증 작업의 region 병렬 처리 개수
- `execution.stop_wait_timeout_seconds`
  - 정지 완료를 기다리는 최대 시간
- `execution.stop_wait_interval_seconds`
  - 정지 상태 재확인 간격
- `retry.max_attempts`
  - OCI API 재시도 횟수
- `retry.base_delay_seconds`
  - 재시도 초기 backoff 시간
- `retry.max_delay_seconds`
  - 재시도 최대 backoff 시간
- `logging.directory`
  - 앱 로그 디렉토리
  - 실행 계정이 쓰기 가능한 경로여야 한다.
- `logging.level`
  - 로그 레벨
  - 운영은 일반적으로 `INFO`, 문제 분석 시 일시적으로 상향 조정한다.

### `config/autostop_compartment_exception.txt`에서 확인할 항목

- 제외할 compartment OCID 또는 exact name을 한 줄씩 기록한다.
- 해당 compartment 본인과 하위 subtree 전체가 AutoStop 대상에서 제외된다.
- 환경마다 compartment 구조가 다르므로 다른 서버에 배포할 때는 이 파일을 그대로 복사해 쓰지 말고 반드시 재검토해야 한다.

### 최초 배포 권장 절차

1. `config/settings.yaml` 의 tenancy, profile, mode, regions, dev base compartment를 환경에 맞게 수정한다.
2. `config/autostop_compartment_exception.txt` 의 제외 대상 compartment를 운영 환경 기준으로 정리한다.
3. `execution.default_dry_run: true` 상태로 먼저 실행한다.
4. `logs/autostop_daily.log` 를 확인해 대상 compartment, region, 제외 범위가 의도대로 잡혔는지 검증한다.
5. 검증이 끝나면 실제 운영 시 `execution.default_dry_run: false` 로 전환한다.

## 설정

기본 설정 파일은 `config/settings.yaml` 이다.

`execution.default_dry_run` 은 기본 실행 동작을 결정하며, `--dry-run` 옵션을 주면 해당 설정값과 관계없이 항상 dry-run으로 실행된다.

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

기본 실행 (`venv` 사용):

```bash
source .venv/bin/activate
python3 -m app.main --config config/settings.yaml
```

기본 실행 (시스템 Python 사용):

```bash
python3 -m app.main --config config/settings.yaml
```

dry-run 강제 (`venv` 사용):

```bash
source .venv/bin/activate
python3 -m app.main --config config/settings.yaml --dry-run
```

dry-run 강제 (시스템 Python 사용):

```bash
python3 -m app.main --config config/settings.yaml --dry-run
```

## cron 예시

매일 18:30 실행 (`venv` 사용):

```cron
30 18 * * * cd ${APP_HOME} && ${APP_HOME}/.venv/bin/python -m app.main --config config/settings.yaml
```

매일 18:30 실행 (시스템 Python 사용):

```cron
30 18 * * * cd ${APP_HOME} && /usr/bin/python3 -m app.main --config config/settings.yaml
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
- 현재 로그는 `logs/autostop_daily.log` 를 하루 단위 덮어쓰기 방식으로 관리하는 운영을 권장한다.
