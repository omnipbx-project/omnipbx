from unittest import TestCase

from pydantic import ValidationError

import support  # noqa: F401

from app.models.inbound_route import InboundRouteCreate
from app.models.queue import QueueCreate
from app.models.ring_group import RingGroupCreate
from app.models.trunk import TrunkCreate
from app.models.working_hours import WorkingHoursCreate


class ModelValidationTests(TestCase):
    def test_trunk_normalizes_names_and_requires_credentials_for_registration(self):
        trunk = TrunkCreate(
            name="SIP_Main",
            provider_name="  Carrier  ",
            host=" sip.example.com ",
            username=" alice ",
            password=" secret ",
        )

        self.assertEqual(trunk.name, "sip_main")
        self.assertEqual(trunk.provider_name, "Carrier")
        self.assertEqual(trunk.host, "sip.example.com")
        self.assertEqual(trunk.username, "alice")

        with self.assertRaises(ValidationError):
            TrunkCreate(name="sip-main", host="sip.example.com", register_enabled=True)

    def test_trunk_rejects_strip_digits_without_outbound_prefix(self):
        with self.assertRaises(ValidationError):
            TrunkCreate(
                name="sip-main",
                host="sip.example.com",
                username="alice",
                password="secret",
                strip_digits=1,
            )

    def test_inbound_route_normalizes_destination_csv_and_rejects_bad_types(self):
        route = InboundRouteCreate(
            name="Main",
            trunk_name="SIP_Main",
            did_pattern=" 555* ",
            destination_type=" Extension ",
            destination_value=" 1001, 1002 ,, ",
        )

        self.assertEqual(route.name, "main")
        self.assertEqual(route.trunk_name, "sip_main")
        self.assertEqual(route.destination_type, "extension")
        self.assertEqual(route.destination_value, "1001, 1002")

        with self.assertRaises(ValidationError):
            InboundRouteCreate(
                name="main",
                trunk_name="sip-main",
                destination_type="shell",
                destination_value="1001",
            )

    def test_queue_and_ring_group_clean_names_members_and_strategies(self):
        queue = QueueCreate(
            name=" Support Team ",
            extension=" 600 ",
            strategy=" RRMEMORY ",
            members=[" 1001 ", "", "1002"],
        )
        group = RingGroupCreate(
            name=" Sales Team ",
            extension=" 700 ",
            ring_strategy=" LINEAR ",
            members=["1003", " 1004 "],
        )

        self.assertEqual(queue.name, "support-team")
        self.assertEqual(queue.strategy, "rrmemory")
        self.assertEqual(queue.members, ["1001", "1002"])
        self.assertEqual(group.name, "sales-team")
        self.assertEqual(group.ring_strategy, "linear")
        self.assertEqual(group.members, ["1003", "1004"])

        with self.assertRaises(ValidationError):
            QueueCreate(name="support", extension="abc", members=["1001"])
        with self.assertRaises(ValidationError):
            RingGroupCreate(name="sales", extension="700", members=["not-numeric"])

    def test_working_hours_normalizes_route_sound_and_validates_day_time(self):
        hours = WorkingHoursCreate(
            name=" Office Hours ",
            start_day=" Monday ",
            end_day=" Friday ",
            start_time="09:00",
            end_time="17:30",
            inbound_route_name=" Main-Route ",
            after_hours_sound=" ",
        )

        self.assertEqual(hours.name, "office-hours")
        self.assertEqual(hours.start_day, "monday")
        self.assertEqual(hours.end_day, "friday")
        self.assertEqual(hours.inbound_route_name, "main-route")
        self.assertIsNone(hours.after_hours_sound)

        with self.assertRaises(ValidationError):
            WorkingHoursCreate(
                name="office",
                start_day="Mon",
                end_day="Friday",
                start_time="9:00",
                end_time="17:00",
                inbound_route_name="main",
            )
