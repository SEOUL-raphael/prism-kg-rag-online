# 폐쇄망 패키징

## 인터넷 연결 PC에서 준비

```powershell
cd D:\gov-rag-portable
.\scripts\package-offline.ps1
```

산출물:

- `wheelhouse\`: Python wheel 묶음
- `dist\govrag_portable-*.whl`: 이 패키지 wheel
- `configs\sources.example.json`: 기관별 설정 템플릿

## 폐쇄망 PC에서 설치

```powershell
cd D:\gov-rag-portable
python -m venv .venv
.\.venv\Scripts\python -m pip install --no-index --find-links .\wheelhouse govrag-portable[pdf]
.\.venv\Scripts\python -m govrag init-db
```

## 모델 반입

기본안은 Ollama Windows 네이티브 런타임입니다.

- 생성 모델 후보: `qwen3:4b`
- 임베딩 후보: `bge-m3`

모델 라이선스와 기관 보안성 검토가 완료된 뒤에만 폐쇄망으로 반입합니다.
