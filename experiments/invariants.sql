SELECT json_agg(row_to_json(checks)) FROM (
SELECT 'available_seat_has_owner' AS test, count(*) AS violations
FROM seats WHERE state='AVAILABLE' AND current_hold_id IS NOT NULL
UNION ALL
SELECT 'state_does_not_match_hold', count(*)
FROM seats s JOIN holds h ON h.hold_id=s.current_hold_id
WHERE (s.state='HELD' AND h.status<>'ACTIVE')
 OR (s.state='CONFIRMED' AND h.status<>'CONFIRMED')
 OR h.status IN ('EXPIRED','CANCELLED')
UNION ALL
SELECT 'partial_live_party', count(*) FROM (
 SELECT h.hold_id FROM holds h LEFT JOIN seats s ON s.current_hold_id=h.hold_id
 WHERE h.status IN ('ACTIVE','CONFIRMED')
 GROUP BY h.hold_id,h.party_size HAVING count(s.seat_id)<>h.party_size
) bad
UNION ALL
SELECT 'non_adjacent_live_party', count(*) FROM (
 SELECT h.hold_id FROM holds h JOIN seats s ON s.current_hold_id=h.hold_id
 WHERE h.status IN ('ACTIVE','CONFIRMED') GROUP BY h.hold_id
 HAVING count(DISTINCT s.section)<>1 OR count(DISTINCT s.row)<>1
 OR max(s.position_in_row)-min(s.position_in_row)+1<>count(*)
) bad
UNION ALL
SELECT 'duplicate_live_request', count(*) FROM (
 SELECT request_id FROM holds WHERE status IN ('ACTIVE','CONFIRMED')
 GROUP BY request_id HAVING count(*)>1
) bad
UNION ALL
SELECT 'seat_in_multiple_live_histories', count(*) FROM (
 SELECT hs.seat_id FROM hold_seats hs JOIN holds h ON h.hold_id=hs.hold_id
 WHERE h.status IN ('ACTIVE','CONFIRMED') GROUP BY hs.seat_id
 HAVING count(DISTINCT h.hold_id)>1
) bad
) checks;
