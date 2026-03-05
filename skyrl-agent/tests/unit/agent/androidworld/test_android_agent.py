"""
Unit and integration tests for AndroidAgent.

Tests static methods (process_raw_output, add_box_token, numpy_to_base64)
and agent behavior with mocked dependencies.
"""

import asyncio
import base64
import io
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import numpy as np
import pytest
from PIL import Image

from skyrl_agent.agents.android.base import AndroidAgent, UITARS_USR_PROMPT_THOUGHT
from skyrl_agent.agents.android.utils import parse_uitars_action, add_box_token, numpy_to_base64, init_messages


# ==================== Static Method Tests (No Mocking Needed) ====================


class TestProcessRawOutput:
    """Test parse_uitars_action() utility function."""
    
    def test_process_raw_output_click(self):
        """Parse click action with coordinates."""
        text = (
            "Thought: I need to click on the Settings icon.\n"
            "Action: click(start_box='(500,300)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "click"
        assert action["touch_point"] == [0.5, 0.3]
        assert "Settings" in thought
    
    def test_process_raw_output_click_large_coords(self):
        """Parse click with larger coordinates."""
        text = (
            "Thought: Clicking the button.\n"
            "Action: click(start_box='(750,850)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "click"
        assert action["touch_point"] == [0.75, 0.85]
    
    def test_process_raw_output_long_press(self):
        """Parse long_press action."""
        text = (
            "Thought: Long press on the item.\n"
            "Action: long_press(start_box='(500,300)', time='2s')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "long_press"
        assert action["touch_point"] == [0.5, 0.3]
    
    def test_process_raw_output_scroll_down(self):
        """Parse scroll with direction calculation - scroll down."""
        text = (
            "Thought: Scroll down to see more.\n"
            "Action: scroll(start_box='(500,800)', end_box='(500,200)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "scroll"
        assert action["direction"] == "down"  # y_start > y_end -> down
    
    def test_process_raw_output_scroll_up(self):
        """Parse scroll - scroll up."""
        text = (
            "Thought: Scroll up.\n"
            "Action: scroll(start_box='(500,200)', end_box='(500,800)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "scroll"
        assert action["direction"] == "up"  # y_start < y_end -> up
    
    def test_process_raw_output_scroll_right(self):
        """Parse scroll - scroll right."""
        text = (
            "Thought: Scroll right.\n"
            "Action: scroll(start_box='(800,500)', end_box='(200,500)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "scroll"
        assert action["direction"] == "right"  # x_start > x_end -> right
    
    def test_process_raw_output_scroll_left(self):
        """Parse scroll - scroll left."""
        text = (
            "Thought: Scroll left.\n"
            "Action: scroll(start_box='(200,500)', end_box='(800,500)')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "scroll"
        assert action["direction"] == "left"  # x_start < x_end -> left
    
    def test_process_raw_output_type(self):
        """Parse type action with content."""
        text = (
            "Thought: Enter the search query.\n"
            "Action: type(content='WiFi settings')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "input_text"
        assert action["text"] == "WiFi settings"
    
    def test_process_raw_output_type_with_newline(self):
        """Parse type action with newline."""
        text = (
            "Thought: Submit the text.\n"
            "Action: type(content='search query\\n')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "input_text"
        assert "search query" in action["text"]
    
    def test_process_raw_output_answer(self):
        """Parse answer action."""
        text = (
            "Thought: Provide the answer.\n"
            "Action: answer(content='The answer is 42')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "answer"
        assert action["text"] == "The answer is 42"
    
    def test_process_raw_output_open_app(self):
        """Parse open_app with app name."""
        text = (
            "Thought: Open the Settings app.\n"
            "Action: open_app(content='Settings')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "open_app"
        assert action["app_name"] == "Settings"
    
    def test_process_raw_output_press_home(self):
        """Parse press_home navigation."""
        text = (
            "Thought: Go to home screen.\n"
            "Action: press_home()"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "navigate_home"
    
    def test_process_raw_output_press_back(self):
        """Parse press_back navigation."""
        text = (
            "Thought: Go back.\n"
            "Action: press_back()"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "navigate_back"
    
    def test_process_raw_output_finished(self):
        """Parse finished action."""
        text = (
            "Thought: Task is complete.\n"
            "Action: finished(content='Done')"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "status"
        assert action["goal_status"] == "complete"
    
    def test_process_raw_output_wait(self):
        """Parse wait action."""
        text = (
            "Thought: Wait for the app to load.\n"
            "Action: wait()"
        )
        action, thought = parse_uitars_action(text)
        
        assert action["action_type"] == "wait"
    
    def test_process_raw_output_invalid(self):
        """Verify ValueError for unsupported actions."""
        text = (
            "Thought: Unknown action.\n"
            "Action: unknown_action(param='value')"
        )
        
        with pytest.raises(ValueError) as exc_info:
            parse_uitars_action(text)
        
        assert "not supported" in str(exc_info.value)
    
    def test_process_raw_output_escaped_characters(self):
        """Parse action with escaped characters."""
        text = (
            "Thought: Click with escaped parens.\n"
            "Action: click(start_box='\\(500,300\\)')"
        )
        # Should handle escaped parentheses
        action, thought = parse_uitars_action(text)
        assert action["action_type"] == "click"


class TestAddBoxToken:
    """Test add_box_token() utility function."""
    
    def test_add_box_token(self):
        """Verify box tokens added to coordinate strings."""
        input_str = (
            "Thought: Click the button.\n"
            "Action: click(start_box='(500,300)')"
        )
        result = add_box_token(input_str)
        
        assert "<|box_start|>" in result
        assert "<|box_end|>" in result
        assert "start_box='<|box_start|>(500,300)<|box_end|>'" in result
    
    def test_add_box_token_multiple_coords(self):
        """Verify box tokens added to multiple coordinate sets."""
        input_str = (
            "Thought: Scroll.\n"
            "Action: scroll(start_box='(500,800)', end_box='(500,200)')"
        )
        result = add_box_token(input_str)
        
        # Both start_box and end_box should have tokens
        assert result.count("<|box_start|>") == 2
        assert result.count("<|box_end|>") == 2
    
    def test_add_box_token_no_action(self):
        """Verify no change when no Action present."""
        input_str = "Just some regular text without action."
        result = add_box_token(input_str)
        
        assert result == input_str
        assert "<|box_start|>" not in result
    
    def test_add_box_token_no_start_box(self):
        """Verify no change when no start_box in action."""
        input_str = (
            "Thought: Wait.\n"
            "Action: wait()"
        )
        result = add_box_token(input_str)
        
        # Should remain unchanged
        assert "<|box_start|>" not in result


class TestNumpyToBase64:
    """Test numpy_to_base64() utility function."""
    
    def test_numpy_to_base64(self):
        """Verify image conversion produces valid base64."""
        # Create a simple test image
        image_array = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        
        result = numpy_to_base64(image_array)
        
        # Verify it's a valid base64 string
        assert isinstance(result, str)
        
        # Verify we can decode it back
        decoded = base64.b64decode(result)
        assert len(decoded) > 0
        
        # Verify it's a valid PNG
        img = Image.open(io.BytesIO(decoded))
        assert img.size == (100, 100)
    
    def test_numpy_to_base64_small_image(self):
        """Verify conversion works for small images."""
        image_array = np.zeros((1, 1, 3), dtype=np.uint8)
        
        result = numpy_to_base64(image_array)
        
        assert isinstance(result, str)
        assert len(result) > 0
    
    def test_numpy_to_base64_different_sizes(self):
        """Verify conversion works for various image sizes."""
        for size in [(10, 10), (100, 200), (1920, 1080)]:
            image_array = np.random.randint(0, 255, (*size, 3), dtype=np.uint8)
            result = numpy_to_base64(image_array)
            
            decoded = base64.b64decode(result)
            img = Image.open(io.BytesIO(decoded))
            assert img.size == (size[1], size[0])  # PIL uses (width, height)


class TestUITARSPrompt:
    """Test the UITARS prompt template."""
    
    def test_prompt_format(self):
        """Verify prompt template contains expected sections."""
        assert "## Output Format" in UITARS_USR_PROMPT_THOUGHT
        assert "## Action Space" in UITARS_USR_PROMPT_THOUGHT
        assert "## Note" in UITARS_USR_PROMPT_THOUGHT
        assert "## User Instruction" in UITARS_USR_PROMPT_THOUGHT
        assert "{instruction}" in UITARS_USR_PROMPT_THOUGHT
    
    def test_prompt_instruction_placeholder(self):
        """Verify instruction placeholder can be filled."""
        instruction = "Open the Settings app"
        formatted = UITARS_USR_PROMPT_THOUGHT.format(instruction=instruction)
        
        assert "Open the Settings app" in formatted
        assert "{instruction}" not in formatted


# ==================== Message Handling Tests (With Mocked Dependencies) ====================


class TestMessageHandling:
    """Test AndroidAgent message handling methods."""
    
    @pytest.fixture
    def agent(self, mock_traj_config, mock_infer_engine, mock_tokenizer, 
              mock_processor, mock_env_handle):
        """Create AndroidAgent with mocked dependencies."""
        # Patch TOOL_REGISTRY to avoid import issues
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        return agent
    
    def test_init_messages(self, agent, sample_instruction):
        """Verify messages initialized from instruction using init_messages util."""
        agent.state.messages = init_messages(sample_instruction)
        
        assert len(agent.state.messages) == len(sample_instruction)
        assert agent.state.messages[0]["role"] == "system"
    
    def test_append_assistant_message(self, agent, sample_instruction):
        """Verify assistant response appended with box tokens."""
        agent.state.messages = init_messages(sample_instruction)
        
        response = (
            "Thought: Click the button.\n"
            "Action: click(start_box='(500,300)')"
        )
        agent.state.messages = agent.append_assistant(agent.state.messages, response)
        
        assert len(agent.state.messages) == len(sample_instruction) + 1
        assert agent.state.messages[-1]["role"] == "assistant"
        # Box tokens should be added
        assert "<|box_start|>" in agent.state.messages[-1]["content"][0]["text"]
    
    def test_append_observation_message(self, agent, sample_instruction, small_test_image):
        """Verify image converted and appended."""
        agent.state.messages = init_messages(sample_instruction)
        agent.state.messages = agent.append_observation(agent.state.messages, small_test_image)
        agent.state.images.append(small_test_image)
        
        assert len(agent.state.messages) == len(sample_instruction) + 1
        assert agent.state.messages[-1]["role"] == "user"
        assert agent.state.messages[-1]["content"][0]["type"] == "image"
        assert "base64" in agent.state.messages[-1]["content"][0]["image"]
        
        # Check state.images
        assert len(agent.state.images) == 1
    
    def test_prepare_input_ids(self, agent, sample_instruction):
        """Verify tokenizer.apply_chat_template called correctly."""
        agent.state.messages = init_messages(sample_instruction)
        
        input_ids = agent.prepare_input_ids(agent.state.messages)
        
        agent.tokenizer.apply_chat_template.assert_called_once()
        assert isinstance(input_ids, list)


# ==================== Integration Tests ====================


class TestAgentStep:
    """Integration tests for AndroidAgent.step() method."""
    
    @pytest.fixture
    def configured_agent(self, mock_traj_config, mock_tokenizer, 
                         mock_processor, mock_env_handle, sample_instruction):
        """Create configured AndroidAgent ready for stepping."""
        # Create mock infer_engine with specific response
        mock_infer_engine = AsyncMock()
        response = (
            "Thought: I need to click on the Settings icon.\n"
            "Action: click(start_box='(500,300)')"
        )
        mock_infer_engine.async_generate_ids = AsyncMock(return_value=(response, "stop"))
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            # Create mock tool
            mock_tool = Mock()
            mock_tool.name = "android_env"
            
            step_obs = {"image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)}
            mock_tool.call = Mock(return_value={
                "image": step_obs["image"],
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            })
            
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
            agent._mock_tool = mock_tool  # Store for assertions
            agent.state.messages = init_messages(sample_instruction)
            
        return agent
    
    @pytest.mark.asyncio
    async def test_step_successful_action(self, configured_agent):
        """Full step: generate -> parse -> execute -> update state."""
        with patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            mock_call.return_value = {
                "image": np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8),
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            }
            
            done, finish_reason, result = await configured_agent.step()
            
            assert done is False
            assert finish_reason is None
            assert configured_agent.state.step_count == 1
    
    @pytest.mark.asyncio
    async def test_step_terminated(self, configured_agent):
        """Verify is_done set when terminated=True."""
        with patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            mock_call.return_value = {
                "image": None,
                "reward": 1.0,
                "terminated": True,
                "truncated": False,
                "info": {"success": True},
            }
            
            done, finish_reason, result = await configured_agent.step()
            
            assert done is True
            assert finish_reason == "FINISH"
            assert configured_agent.state.is_done is True
            assert result == 1.0
    
    @pytest.mark.asyncio
    async def test_step_parse_error_recovery(self, mock_traj_config, mock_tokenizer,
                                             mock_processor, mock_env_handle, sample_instruction):
        """Verify fallback action on parse error."""
        # Create agent with invalid response
        mock_infer_engine = AsyncMock()
        invalid_response = "This is not a valid action format"
        mock_infer_engine.async_generate_ids = AsyncMock(return_value=(invalid_response, "stop"))
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
            agent.state.messages = init_messages(sample_instruction)
        
        with patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            mock_call.return_value = {
                "image": None,
                "reward": 0.0,
                "terminated": True,
                "truncated": False,
                "info": {},
            }
            
            done, finish_reason, result = await agent.step()
            
            # Should have called tool with fallback action
            mock_call.assert_called_once()
            call_args = mock_call.call_args
            action_dict = call_args[0][1]  # Second positional arg
            assert action_dict["action_type"] == "status"
            assert agent.state.format_reward == -1.0


class TestAgentRun:
    """Integration tests for AndroidAgent.run() method."""
    
    @pytest.mark.asyncio
    async def test_run_until_done(self, mock_traj_config, mock_tokenizer,
                                   mock_processor, mock_env_handle, sample_instruction):
        """Verify run loop with multiple steps."""
        # Create responses that lead to termination after 2 steps
        responses = [
            ("Thought: First step.\nAction: click(start_box='(500,300)')", "stop"),
            ("Thought: Complete.\nAction: finished(content='done')", "stop"),
        ]
        
        mock_infer_engine = AsyncMock()
        mock_infer_engine.async_generate_ids = AsyncMock(side_effect=responses)
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        
        step_results = [
            {"image": np.random.randint(0, 255, (10, 10, 3), dtype=np.uint8),
             "reward": 0.0, "terminated": False, "truncated": False, "info": {}},
            {"image": None, "reward": 1.0, "terminated": True, "truncated": False, "info": {}},
        ]
        
        with patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            mock_call.side_effect = step_results
            
            finish_reason, result = await agent.run(sample_instruction)
            
            assert finish_reason == "FINISH"
            assert agent.state.step_count == 2
    
    @pytest.mark.asyncio
    async def test_run_max_iterations(self, mock_traj_config, mock_tokenizer,
                                       mock_processor, mock_env_handle, sample_instruction):
        """Verify run stops at max_iterations."""
        # Set low max_iterations
        mock_traj_config.max_iterations = 2
        
        mock_infer_engine = AsyncMock()
        # Always return non-terminating action
        response = ("Thought: Continue.\nAction: click(start_box='(500,300)')", "stop")
        mock_infer_engine.async_generate_ids = AsyncMock(return_value=response)
        
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        
        with patch('skyrl_agent.agents.android.base.call_sync_from_async') as mock_call:
            mock_call.return_value = {
                "image": np.random.randint(0, 255, (10, 10, 3), dtype=np.uint8),
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "info": {},
            }
            
            finish_reason, result = await agent.run(sample_instruction)
            
            assert finish_reason == "max_iterations_reached"
            assert agent.state.step_count == 2


class TestAgentGetters:
    """Test AndroidAgent getter methods."""
    
    @pytest.fixture
    def agent_with_history(self, mock_traj_config, mock_infer_engine, mock_tokenizer,
                           mock_processor, mock_env_handle, sample_instruction, small_test_image):
        """Create agent with some history."""
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        
        # Initialize messages using new API
        agent.state.messages = init_messages(sample_instruction)
        agent.state.messages = agent.append_assistant(agent.state.messages, "Thought: Test.\nAction: wait()")
        agent.state.messages = agent.append_observation(agent.state.messages, small_test_image)
        agent.state.images.append(small_test_image)
        agent.state.reward = 0.5
        agent.state.format_reward = -0.1
        
        return agent
    
    def test_get_messages(self, agent_with_history):
        """Verify get_messages returns conversation history."""
        messages = agent_with_history.get_messages()
        
        assert isinstance(messages, list)
        assert len(messages) > 0
    
    def test_get_history_images(self, agent_with_history):
        """Verify get_history_images returns screenshots."""
        images = agent_with_history.get_history_images()
        
        assert isinstance(images, list)
        assert len(images) == 1
    
    def test_get_reward(self, agent_with_history):
        """Verify get_reward returns accumulated reward."""
        reward = agent_with_history.get_reward()
        
        assert reward == 0.5
    
    def test_get_format_reward(self, agent_with_history):
        """Verify get_format_reward returns format penalty."""
        format_reward = agent_with_history.get_format_reward()
        
        assert format_reward == -0.1


# ==================== Process For Training Tests ====================


class TestProcessForTraining:
    """Test AndroidAgent.process_for_training() method."""
    
    @pytest.fixture
    def agent(self, mock_traj_config, mock_infer_engine, mock_tokenizer, 
              mock_processor, mock_env_handle):
        """Create AndroidAgent with mocked dependencies."""
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        return agent
    
    @pytest.fixture
    def mock_processor_for_training(self):
        """Mock processor that returns realistic tensors for training."""
        import torch
        
        processor = Mock()
        
        def process_fn(images, texts, add_special_tokens=False, return_tensors="pt"):
            seq_len = 20
            result = {
                'input_ids': torch.arange(seq_len, dtype=torch.long).unsqueeze(0),
                'attention_mask': torch.ones((1, seq_len), dtype=torch.long),
            }
            
            if images is not None and len(images) > 0:
                result['pixel_values'] = torch.zeros((len(images), 3, 224, 224))
                result['image_grid_thw'] = torch.tensor([[1, 14, 14]] * len(images))
            
            return result
        
        processor.side_effect = process_fn
        return processor
    
    def test_process_for_training_returns_empty_without_processor(self, agent):
        """Verify returns empty dict when processor is None."""
        agent.processor = None
        
        messages = [{"role": "user", "content": [{"type": "text", "text": "test"}]}]
        result = agent.process_for_training(messages)
        
        assert result == {}
    
    def test_process_for_training_labels_masking(self, agent, mock_processor_for_training):
        """Verify system/user labels are -100, assistant labels are actual tokens."""
        import torch
        import sys
        
        # Create mock module for qwen_vl_utils
        mock_qwen_vl = MagicMock()
        mock_qwen_vl.process_vision_info = MagicMock(return_value=([], [], {}))
        sys.modules['qwen_vl_utils'] = mock_qwen_vl
        
        agent.processor = mock_processor_for_training
        
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "You are helpful."}]},
            {"role": "user", "content": [{"type": "text", "text": "Do task"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Thought: OK\nAction: wait()"}]},
        ]
        
        try:
            result = agent.process_for_training(messages)
            
            assert "input_ids" in result
            assert "labels" in result
            
            # Labels should have -100 for first two messages (system + user = 40 tokens)
            # and actual tokens for assistant (20 tokens)
            labels = result["labels"]
            
            # First 40 tokens (system + user) should be -100
            assert (labels[:40] == -100).all(), "System/user labels should be -100"
            # Last 20 tokens (assistant) should NOT be -100
            assert (labels[40:] != -100).all(), "Assistant labels should be actual tokens"
        finally:
            # Clean up mock module
            if 'qwen_vl_utils' in sys.modules:
                del sys.modules['qwen_vl_utils']
    
    def test_process_for_training_with_images(self, agent, mock_processor_for_training):
        """Verify images are processed and pixel_values returned."""
        import torch
        import sys
        from PIL import Image
        
        # Mock process_vision_info to return a PIL image
        mock_image = Image.new('RGB', (100, 100))
        
        # Create mock module for qwen_vl_utils
        mock_qwen_vl = MagicMock()
        mock_qwen_vl.process_vision_info = MagicMock(return_value=([mock_image], [], {}))
        sys.modules['qwen_vl_utils'] = mock_qwen_vl
        
        agent.processor = mock_processor_for_training
        
        messages = [
            {"role": "user", "content": [
                {"type": "image", "image": "data:image/png;base64,abc123"},
            ]},
        ]
        
        try:
            result = agent.process_for_training(messages)
            
            assert "pixel_values" in result
            assert "image_grid_thw" in result
            assert result["pixel_values"].shape[0] == 1  # One image
        finally:
            if 'qwen_vl_utils' in sys.modules:
                del sys.modules['qwen_vl_utils']
    
    def test_process_for_training_concatenates_multiple_messages(self, agent, mock_processor_for_training):
        """Verify tensors from multiple messages are concatenated."""
        import torch
        import sys
        
        # Create mock module for qwen_vl_utils
        mock_qwen_vl = MagicMock()
        mock_qwen_vl.process_vision_info = MagicMock(return_value=([], [], {}))
        sys.modules['qwen_vl_utils'] = mock_qwen_vl
        
        agent.processor = mock_processor_for_training
        
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "System"}]},
            {"role": "user", "content": [{"type": "text", "text": "User"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Assistant"}]},
            {"role": "user", "content": [{"type": "text", "text": "User2"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Assistant2"}]},
        ]
        
        try:
            result = agent.process_for_training(messages)
            
            # Each message produces 20 tokens, 5 messages = 100 tokens
            assert result["input_ids"].shape[0] == 100
            assert result["labels"].shape[0] == 100
            assert result["attention_mask"].shape[0] == 100
        finally:
            if 'qwen_vl_utils' in sys.modules:
                del sys.modules['qwen_vl_utils']
    
    def test_process_for_training_fails_loudly_on_vision_error(self, agent, mock_processor_for_training):
        """Verify exception propagates when process_vision_info fails."""
        import sys
        
        # Create mock module for qwen_vl_utils that raises error
        mock_qwen_vl = MagicMock()
        mock_qwen_vl.process_vision_info = MagicMock(side_effect=ValueError("Failed to process image"))
        sys.modules['qwen_vl_utils'] = mock_qwen_vl
        
        agent.processor = mock_processor_for_training
        
        messages = [
            {"role": "user", "content": [
                {"type": "image", "image": "data:image/png;base64,invalid"},
            ]},
        ]
        
        try:
            # Should raise, not silently fail
            with pytest.raises(ValueError) as exc_info:
                agent.process_for_training(messages)
            
            assert "Failed to process image" in str(exc_info.value)
        finally:
            if 'qwen_vl_utils' in sys.modules:
                del sys.modules['qwen_vl_utils']
    
    def test_process_for_training_empty_messages(self, agent, mock_processor_for_training):
        """Verify empty messages returns empty result."""
        import sys
        
        # Create mock module for qwen_vl_utils
        mock_qwen_vl = MagicMock()
        mock_qwen_vl.process_vision_info = MagicMock(return_value=([], [], {}))
        sys.modules['qwen_vl_utils'] = mock_qwen_vl
        
        agent.processor = mock_processor_for_training
        
        try:
            result = agent.process_for_training([])
            assert result == {}
        finally:
            if 'qwen_vl_utils' in sys.modules:
                del sys.modules['qwen_vl_utils']


class TestTrainingAccumulator:
    """Test TrainingAccumulator via AndroidAgent.training."""
    
    @pytest.fixture
    def agent(self, mock_traj_config, mock_infer_engine, mock_tokenizer, 
              mock_processor, mock_env_handle):
        """Create AndroidAgent with mocked dependencies."""
        with patch('skyrl_agent.agents.android.base.TOOL_REGISTRY') as mock_registry:
            mock_tool = Mock()
            mock_tool.name = "android_env"
            mock_registry.__contains__ = Mock(return_value=True)
            mock_registry.__getitem__ = Mock(return_value=lambda: mock_tool)
            
            agent = AndroidAgent(
                traj_config=mock_traj_config,
                infer_engine=mock_infer_engine,
                tokenizer=mock_tokenizer,
                processor=mock_processor,
                env_handle=mock_env_handle,
            )
        return agent
    
    def test_accumulate_tensors_concatenates_input_ids(self, agent):
        """Verify train_input_ids are concatenated correctly via TrainingAccumulator."""
        import torch
        
        # Initial state has empty tensors
        assert agent.training._train_input_ids.shape[0] == 0
        
        # Accumulate first batch using internal _accumulate method
        batch1 = {
            "train_input_ids": torch.tensor([1, 2, 3]),
            "train_labels": torch.tensor([-100, -100, -100]),
            "train_attention_mask": torch.tensor([1, 1, 1]),
        }
        agent.training._accumulate(batch1)
        
        assert agent.training._train_input_ids.shape[0] == 3
        
        # Accumulate second batch
        batch2 = {
            "train_input_ids": torch.tensor([4, 5]),
            "train_labels": torch.tensor([4, 5]),
            "train_attention_mask": torch.tensor([1, 1]),
        }
        agent.training._accumulate(batch2)
        
        assert agent.training._train_input_ids.shape[0] == 5
        assert list(agent.training._train_input_ids) == [1, 2, 3, 4, 5]
    
    def test_accumulate_tensors_handles_pixel_values(self, agent):
        """Verify train_pixel_values are accumulated correctly."""
        import torch
        
        assert agent.training._train_pixel_values is None
        
        # First batch with pixel values
        batch1 = {
            "train_input_ids": torch.tensor([1, 2]),
            "train_labels": torch.tensor([-100, -100]),
            "train_attention_mask": torch.tensor([1, 1]),
            "train_pixel_values": torch.zeros((1, 3, 224, 224)),
            "train_image_grid_thw": torch.tensor([[1, 14, 14]]),
        }
        agent.training._accumulate(batch1)
        
        assert agent.training._train_pixel_values.shape[0] == 1
        
        # Second batch with more pixel values
        batch2 = {
            "train_input_ids": torch.tensor([3, 4]),
            "train_labels": torch.tensor([3, 4]),
            "train_attention_mask": torch.tensor([1, 1]),
            "train_pixel_values": torch.zeros((2, 3, 224, 224)),
            "train_image_grid_thw": torch.tensor([[1, 14, 14], [1, 14, 14]]),
        }
        agent.training._accumulate(batch2)
        
        assert agent.training._train_pixel_values.shape[0] == 3
        assert agent.training._train_image_grid_thw.shape[0] == 3
    
    def test_accumulate_tensors_handles_empty_dict(self, agent):
        """Verify empty dict doesn't modify state."""
        import torch
        
        # Add some initial tensors
        batch = {
            "train_input_ids": torch.tensor([1, 2, 3]),
            "train_labels": torch.tensor([-100, -100, -100]),
            "train_attention_mask": torch.tensor([1, 1, 1]),
        }
        agent.training._accumulate(batch)
        
        initial_len = agent.training._train_input_ids.shape[0]
        
        # Accumulate empty dict
        agent.training._accumulate({})
        
        # Should be unchanged
        assert agent.training._train_input_ids.shape[0] == initial_len
