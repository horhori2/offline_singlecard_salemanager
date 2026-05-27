# GET /v1/pay-order/seller/product-orders/last-changed-statuses - 변경 상품 주문 내역 조회

결제완료부터 배송완료, 클레임(취소·반품·교환) 분기까지 이어지는 주문 상태 머신에서, 지정한 시간 범위에 상태가 바뀐 상품 주문들의 변경 이력만 추려서 식별 정보를 받아오는 폴링용 조회 endpoint입니다. 운영 환경에서는 주문 관리 시스템이 본 API를 일정 주기(예: 5~15분)로 호출해 변경분만 수집한 뒤 상세 조회 API와 결합해 주문 데이터를 동기화하는 방식이 일반적입니다. lastChangedFrom은 필수이며 lastChangedTo를 생략하면 시작 시각으로부터 24시간 후까지가 자동 적용되므로 폴링 주기보다 짧지 않게 범위를 잡아 누락을 방지합니다. 응답 항목 수가 최대 응답 개수(기본 및 상한 300건)를 초과하면 more 객체가 함께 내려오며, moreFrom과 moreSequence를 다음 요청의 시작 일시와 시퀀스로 전달해 같은 일시에 묶인 항목을 중복 없이 이어 받아야 합니다. 변경 구분은 lastChangedType으로 좁힐 수 있고 limitCount는 300을 초과해 지정해도 300으로 캡됩니다. 400은 일시 형식이나 페이징 파라미터 오류, 500은 일시적 서버 장애 가능성이 높으므로 클라이언트는 동일 구간을 재요청하기 전에 백오프를 두고 무한 루프 방지를 위해 최대 시도 횟수를 제한해야 합니다.

> Base URL: https://api.commerce.naver.com/external

### 요청 파라미터

| 이름 | 위치 | 타입 | 필수 | 설명 |
|------|------|------|:----:|------|
| lastChangedFrom | query | string(date-time) | 필수 | 조회 시작 일시(inclusive) |
| lastChangedTo | query | string(date-time) |  | 조회 종료 일시(inclusive). 생략 시 lastChangedFrom으로부터 24시간 후로 자동 지정됩니다. |
| lastChangedType | query | string |  | 최종 변경 구분 |
| moreSequence | query | string |  | moreSequence 사용법은 API 설명을 참고합니다. 임의의 값 입력 시 예기치 않은 결과가 제공될 수 있습니다. |
| limitCount | query | integer |  | 조회 응답 개수 제한. 생략하거나 300을 초과하는 값을 입력하면 최대 300개의 내역을 제공합니다. |

### 응답 스키마

| 이름 | 위치 | 타입 | 필수 | 설명 |
|------|------|------|:----:|------|
| timestamp | - | string(date-time) |  |  |
| traceId | - | string | 필수 |  |
| data | - | object |  |  |
| data.count | - | integer | 필수 |  |
| data.more | - | object |  | 일시 범위로 목록을 요청하는 API는 최대 응답 개수를 제한합니다. 만약 응답할 항목의 개수가 최대 응답 개수보다 많으면 최대 응답 개수만큼의 일부만 응답으로 제공됩니다. 요청한 범위 내의 항목을 모두 제공하지 못한 경우 more 객체가 응답에 포함됩니다. more 객체의 moreFrom과 moreSequence 값을 사용해 나머지 항목을 요청할 수 있습니다.<br>응답 목록은 시간순으로 정렬되어 있습니다. moreFrom 값은 최대 응답 개수 제한 때문에 제공하지 못한 항목 중 첫 항목의 일시를 의미합니다. 이 값을 새로운 조회 요청의 조회 시작 일시로 지정하면 다음 목록을 이어서 조회할 수 있습니다.<br>이때 같은 일시에 해당하는 항목이 두 개 이상 존재할 수 있기 때문에 같은 일시의 값을 구체적으로 구분하기 위해서 moreSequence 값을 제공합니다. 새로운 요청에서 moreSequence 값을 사용하면 특정 필드 값이 moreSequence 이상인 항목만 제공되어 중복 응답을 피할 수 있습니다. |
| data.more.… | - | - |  | 하위 구조 생략 (상세는 OAS 참조) |
| data.lastChangeStatuses | - | array | 필수 | 이 구조체는 주문건의 변경 상품 주문 정보를 표현하는 구조체입니다.<br>전체 주문건에서 지정된 조회 조건에 해당하는 주문건을 식별할 수 있는 일부 정보를 표현합니다.<br>- 이 구조체는 API 호출에 대한 응답으로만 사용합니다.<br>- 구조체의 객체 1개는 상품주문번호 1개를 표현합니다. |
| data.lastChangeStatuses.… | - | - |  | 하위 구조 생략 (상세는 OAS 참조) |

### 에러 코드

| 상태 코드 | 설명 |
|-----------|------|
| 400 |  |
| 500 |  |

### 호출 예시

```bash
curl -X GET 'https://api.commerce.naver.com/external/v1/pay-order/seller/product-orders/last-changed-statuses?lastChangedFrom={lastChangedFrom}' \
  -H 'Authorization: Bearer {access_token}'
```