package organization

import "encoding/json"

func encodeTags(tags []string) (string, error) {
	return encodeStringList(tags)
}

func encodeStringList(values []string) (string, error) {
	if values == nil {
		values = []string{}
	}
	encoded, err := json.Marshal(values)
	if err != nil {
		return "", err
	}
	return string(encoded), nil
}

func decodeTags(value string) []string {
	return decodeStringList(value)
}

func decodeStringList(value string) []string {
	var values []string
	if err := json.Unmarshal([]byte(value), &values); err != nil {
		return []string{}
	}
	if values == nil {
		return []string{}
	}
	return values
}
