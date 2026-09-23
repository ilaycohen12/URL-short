{{- define "url-short.labels" -}}
app.kubernetes.io/part-of: url-short
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
