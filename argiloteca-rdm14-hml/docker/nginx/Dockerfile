FROM nginx:stable-alpine@sha256:985220252f3863977e468f611ef118ebd01421289dd86ee1ae99cb068c3bce2b
COPY nginx.conf /etc/nginx/nginx.conf
ENV HML_HTTPS_PORT=5101
COPY conf.d/default.conf /etc/nginx/templates/default.conf.template
COPY test.key /etc/ssl/private/test.key
COPY test.crt /etc/ssl/certs/test.crt
