# OCI AutoStop Python App

Oracle Linux 환경에서 cron으로 실행하는 OCI AutoStop 애플리케이션이다. tenancy 전체 또는 DEV 기준 subtree 범위를 조회하고, 예외 compartment subtree를 제외한 뒤 Compute Instance, DB Node, Autonomous Database 중 실행 중인 리소스만 정지한다.

## 주요 특징

- OCI Python SDK 기반 구현
- `dev` / `prod` 설정 기반 전환
- compartment exception subtree 제외
- dry-run 지원
- 재시도와 backoff 적용
- 날짜별 로그 파일과 실행별 summary 파일 생성
- root compartment 직접 생성 리소스 포함 여부 제어
- 일부 리소스 실패가 전체 프로세스를 즉시 중단시키지 않도록 설계

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

기본 설정 파일은 [config/settings.yaml](/home/opc/workspace_autostop/config/settings.yaml) 이다.

- `scope.mode: dev`
  - root 바로 아래 direct child인 `dev-base` 또는 지정 OCID를 base subtree로 사용
  - tenancy 전체 조회를 하지 않음
- `scope.mode: prod`
  - tenancy 전체 subtree를 조회
  - exception 파일을 반드시 반영
- `scope.include_root_resources`
  - `true`면 root compartment 직접 생성 리소스도 대상에 포함

예외 파일은 [config/autostop_compartment_exception.txt](/home/opc/workspace_autostop/config/autostop_compartment_exception.txt) 이며 주석과 빈 줄을 허용한다.

## 실행

```bash
python -m app.main --config config/settings.yaml
```

dry-run 강제:

```bash
python -m app.main --config config/settings.yaml --dry-run
```

## cron 예시

매일 18:30 실행:

```cron
30 18 * * * cd /home/opc/workspace_autostop && /home/opc/workspace_autostop/.venv/bin/python -m app.main --config config/settings.yaml >> /home/opc/workspace_autostop/logs/cron_stdout.log 2>&1
```

## 동작 순서

1. 설정 로드
2. OCI 설정 로드 및 tenancy 확인
3. 모드에 따라 대상 compartment 범위 결정
4. exception subtree 제외
5. region별, compartment별로 Compute / DB Node / ADB 조회
6. 상태에 따라 stop 또는 skip
7. stop 후 상태 재확인
8. 로그 및 summary 파일 저장

## 상태 처리 기준

- Compute: `RUNNING` stop, `STOPPED` skip, `STOPPING/STARTING/PROVISIONING` transition skip
- DB Node: `AVAILABLE` stop, `STOPPED` skip, `STOPPING/STARTING/PROVISIONING` transition skip
- ADB: `AVAILABLE` stop, `STOPPED` skip, `STOPPING/STARTING/PROVISIONING/SCALING` transition skip

## 운영 팁

- 최초 운영은 `dev` + `default_dry_run: true` 로 시작
- `dev-base` 하위에 테스트용 compartment를 만들어 exception subtree 동작을 검증
- summary 파일의 `failed` 와 `errors` 항목을 함께 확인
- region 추가 시 `oci.regions` 배열만 확장하면 된다
