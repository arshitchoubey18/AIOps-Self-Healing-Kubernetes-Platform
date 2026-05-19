{{- define "aio.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "aio.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "aio.image" -}}
{{- printf "%s/%s:%s" .Values.global.imageRegistry .repository .Values.global.imageTag -}}
{{- end -}}

