# KLFA Score Manager

FastAPI + SQLite 기반 대회 성적 관리 웹앱입니다.

## 포함된 파일

- `score_web_app.py`: 웹앱 본체
- `score_manager_app.py`: 같은 `score_web.db`를 사용하는 데스크톱 앱
- `requirements_web.txt`: Python 패키지 목록
- `start_score_web.bat`: Windows 로컬 실행용
- `Procfile`: 서버 배포용 실행 명령

## 로컬 실행

```bash
python -m pip install -r requirements_web.txt
python -m uvicorn score_web_app:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://127.0.0.1:8000/`로 접속합니다.

## 데이터 파일

실제 대회 데이터는 `score_web.db`에 저장됩니다. 이 파일은 개인정보와 실제 성적을 포함할 수 있으므로 GitHub에는 올리지 않습니다.

운영 서버에 배포할 때는 GitHub에서 코드를 받은 뒤, 기존 `score_web.db`를 서버 폴더에 별도로 복사해서 사용합니다.
