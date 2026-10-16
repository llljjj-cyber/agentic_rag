FROM python:3.10-slim
WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_SPEC=torch==2.9.1

COPY backend/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip -i ${PIP_INDEX_URL} \
 && pip install --no-cache-dir ${TORCH_SPEC} \
      --index-url ${TORCH_INDEX_URL} \
      --extra-index-url ${PIP_INDEX_URL} \
 && pip install --no-cache-dir -r requirements.txt \
      -i ${PIP_INDEX_URL} \
 && python -c "import torch; assert not torch.cuda.is_available(), torch.__version__"
 
COPY backend ./backend
COPY worker ./worker
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
